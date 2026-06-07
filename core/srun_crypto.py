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
STD_BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def s_func(a, b):
    """JS s() - 字符串转32位整数数组"""
    c = len(a); v = []
    for i in range(0, c, 4):
        val = (ord(a[i]) if i<c else 0) | ((ord(a[i+1]) if i+1<c else 0)<<8) | ((ord(a[i+2]) if i+2<c else 0)<<16) | ((ord(a[i+3]) if i+3<c else 0)<<24)
        v.append(val & 0xFFFFFFFF)
    if b: v.append(c)
    return v


def l_func(a, b):
    """JS l() - 32位整数数组转字符串"""
    d = len(a)
    if b:
        ct = (d-1)<<2; m = a[d-1]
        if m < ct-3 or m > ct: return None
        ct = m
    r = []
    for val in a: r += [chr(val&0xFF), chr((val>>8)&0xFF), chr((val>>16)&0xFF), chr((val>>24)&0xFF)]
    s = "".join(r)
    return s[:ct] if b else s


def xxtea_encode(str_data, key):
    """XXTEA 加密，与 Portal.js encode() 完全一致"""
    if not str_data: return ""
    v = s_func(str_data, True); k = s_func(key, False)
    while len(k) < 4: k.append(0)
    n = len(v)-1; z = v[n]; y = v[0]
    delta = 0x9E3779B9; q = 6 + 52//(n+1); d = 0
    for _ in range(q):
        d = (d + delta) & 0xFFFFFFFF
        e = (d >> 2) & 3
        p = 0
        while p < n:
            y = v[p+1]
            m = ((z>>5)^(y<<2)) & 0xFFFFFFFF
            m = (m + ((y>>3)^(z<<4)^(d^y))) & 0xFFFFFFFF
            m = (m + (k[(p&3)^e]^z)) & 0xFFFFFFFF
            v[p] = (v[p] + m) & 0xFFFFFFFF
            z = v[p]
            p += 1
        y = v[0]
        m = ((z>>5)^(y<<2)) & 0xFFFFFFFF
        m = (m + ((y>>3)^(z<<4)^(d^y))) & 0xFFFFFFFF
        m = (m + (k[(p&3)^e]^z)) & 0xFFFFFFFF
        v[n] = (v[n] + m) & 0xFFFFFFFF
        z = v[n]
    return l_func(v, False)


def custom_base64_encode(data: bytes) -> str:
    """使用深澜自定义字母表 Base64 编码"""
    import base64
    SRUN_ALPHA = SRUN_BASE64_ALPHABET
    result = []; i = 0
    while i < len(data):
        b1 = data[i]; b2 = data[i+1] if i+1<len(data) else 0; b3 = data[i+2] if i+2<len(data) else 0
        c1 = b1>>2; c2 = ((b1&3)<<4)|(b2>>4); c3 = ((b2&0xF)<<2)|(b3>>6); c4 = b3&0x3F
        rem = len(data)-i
        if rem==1: result += [SRUN_ALPHA[c1], SRUN_ALPHA[c2], "=", "="]
        elif rem==2: result += [SRUN_ALPHA[c1], SRUN_ALPHA[c2], SRUN_ALPHA[c3], "="]
        else: result += [SRUN_ALPHA[c1], SRUN_ALPHA[c2], SRUN_ALPHA[c3], SRUN_ALPHA[c4]]
        i += 3
    return "".join(result)


def custom_base64_decode(s: str) -> bytes:
    """解码深澜自定义 Base64"""
    import base64
    t = str.maketrans(SRUN_BASE64_ALPHABET, STD_BASE64_ALPHABET)
    return base64.b64decode(s.translate(t))


def calc_hmd5(password: str, token: str) -> str:
    """hmd5 = HMAC-MD5(key=token, data=password)"""
    return hmac.new(token.encode(), password.encode(), hashlib.md5).hexdigest()


def calc_sha1(s: str) -> str:
    """SHA1 摘要"""
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def encode_srun_info(info_dict: dict, token: str) -> str:
    """编码用户信息为 {SRBX1} 格式"""
    info_json = json.dumps(info_dict, separators=(",", ":"))
    encrypted_str = xxtea_encode(info_json, token)
    b64encoded = custom_base64_encode(encrypted_str.encode("latin-1"))
    return "{SRBX1}" + b64encoded


def calc_chksum(token: str, username: str, hmd5: str, ac_id: str,
                ip: str, n: int, typ: int, info: str) -> str:
    """计算 chksum = SHA1(token+username+token+hmd5+...+token+info)"""
    s = (token + username + token + hmd5 + token + ac_id +
         token + ip + token + str(n) + token + str(typ) + token + info)
    return calc_sha1(s)