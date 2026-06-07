"""
深澜 srun_portal 加密模块
实现 XXTEA 加密、自定义 Base64、HMAC-MD5、SHA1 等协议所需算法
"""
import hashlib
import hmac
import json
import struct

# 深澜自定义 Base64 字母表
SRUN_BASE64_ALPHABET = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"

# 标准 Base64 字母表（用于对照）
STD_BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def custom_base64_encode(data: bytes) -> str:
    """使用深澜自定义字母表进行 Base64 编码"""
    # 先用标准 Base64 编码
    import base64
    std_result = base64.b64encode(data).decode("ascii")
    # 替换字母表
    translation_table = str.maketrans(STD_BASE64_ALPHABET, SRUN_BASE64_ALPHABET)
    return std_result.translate(translation_table)


def custom_base64_decode(s: str) -> bytes:
    """解码深澜自定义 Base64"""
    import base64
    translation_table = str.maketrans(SRUN_BASE64_ALPHABET, STD_BASE64_ALPHABET)
    std_str = s.translate(translation_table)
    return base64.b64decode(std_str)


def _xxtea_encode(str_data: str, key: str) -> bytes:
    """XXTEA 加密（Corrected Block TEA）
    与 Portal.js 中的 encode() 函数完全一致
    """
    if not str_data:
        return b""

    # s() - 将字符串转为 32 位小端整数数组，末尾附长度
    v = _str_to_uint32_array(str_data, append_length=True)
    k = _str_to_uint32_array(key, append_length=False)
    if len(k) < 4:
        k = k + [0] * (4 - len(k))

    n = len(v) - 1
    z = v[n]
    y = v[0]
    delta = 0x9E3779B9
    q = 6 + 52 // (n + 1)
    d = 0

    for _ in range(q):
        d = (d + delta) & 0xFFFFFFFF
        e = (d >> 2) & 3
        for p in range(n):
            y = v[p + 1]
            m = ((z >> 5) ^ (y << 2)) & 0xFFFFFFFF
            m = (m + ((y >> 3) ^ (z << 4) ^ (d ^ y))) & 0xFFFFFFFF
            m = (m + (k[(p & 3) ^ e] ^ z)) & 0xFFFFFFFF
            v[p] = (v[p] + m) & 0xFFFFFFFF
            z = v[p]

        y = v[0]
        m = ((z >> 5) ^ (y << 2)) & 0xFFFFFFFF
        m = (m + ((y >> 3) ^ (z << 4) ^ (d ^ y))) & 0xFFFFFFFF
        m = (m + (k[(p & 3) ^ e] ^ z)) & 0xFFFFFFFF
        v[n] = (v[n] + m) & 0xFFFFFFFF
        z = v[n]

    # l() - 将整数数组转回字节串
    return _uint32_array_to_bytes(v, trim_length=False)


def _str_to_uint32_array(s: str, append_length: bool = False) -> list:
    """将字符串转为 32 位小端整数数组"""
    data = s.encode("utf-8")
    v = []
    for i in range(0, len(data), 4):
        chunk = data[i:i + 4]
        val = 0
        for j in range(len(chunk)):
            val |= chunk[j] << (j * 8)
        v.append(val)
    if append_length:
        v.append(len(data))
    return v


def _uint32_array_to_bytes(v: list, trim_length: bool = False) -> bytes:
    """将 32 位整数数组转回字节串"""
    result = bytearray()
    for val in v:
        result.extend(struct.pack("<I", val & 0xFFFFFFFF))

    if trim_length:
        # 获取末尾编码的长度信息
        data_len = v[-1]
        if data_len > len(result) - 4:
            return None
        return bytes(result[:data_len])
    return bytes(result)


def calc_hmd5(password: str, token: str) -> str:
    """计算 hmd5 = HMAC-MD5(key=token, data=password)
    与 Portal.js 中 md5(password, token) 一致
    """
    key_bytes = token.encode("utf-8")
    data_bytes = password.encode("utf-8")
    h = hmac.new(key_bytes, data_bytes, hashlib.md5)
    return h.hexdigest()


def calc_sha1(s: str) -> str:
    """计算 SHA1 摘要"""
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def encode_srun_info(info_dict: dict, token: str) -> str:
    """编码用户信息为 {SRBX1} 格式
    info_dict: {username, password, ip, acid, enc_ver}
    """
    info_json = json.dumps(info_dict, separators=(",", ":"))
    encrypted = _xxtea_encode(info_json, token)
    b64encoded = custom_base64_encode(encrypted)
    return "{SRBX1}" + b64encoded


def calc_chksum(token: str, username: str, hmd5: str, ac_id: str,
                ip: str, n: int, typ: int, info: str) -> str:
    """计算 chksum = SHA1(token+username+token+hmd5+...+token+info)"""
    s = (token + username +
         token + hmd5 +
         token + ac_id +
         token + ip +
         token + str(n) +
         token + str(typ) +
         token + info)
    return calc_sha1(s)
