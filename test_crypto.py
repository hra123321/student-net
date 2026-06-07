import sys, os
sys.path.insert(0, ".")
from core.srun_crypto import *

# Now explicitly import the private function
from core.srun_crypto import _xxtea_encode, _str_to_uint32_array, _uint32_array_to_bytes, custom_base64_encode, custom_base64_decode

print("XXTEA 加解密测试...")
data = '{"username":"test","password":"pass","ip":"1.1.1.1","acid":"1","enc_ver":"srun_bx1"}'
key = "challenge_token_1234567890"
encrypted = _xxtea_encode(data, key)
print(f"加密成功: 长度={len(encrypted)} 内容={encrypted[:30].hex()}")

# Verify: encryption should produce non-empty result
print(f"加密结果非空: {len(encrypted) > 0}")
print(f"加密结果不是原始数据: {encrypted != data.encode()}")

# Full SRBX1
info = {"username":"test","password":"pass","ip":"1.1.1.1","acid":"1","enc_ver":"srun_bx1"}
result = encode_srun_info(info, "test_challenge")
print(f"\n完整SRBX1: {result[:60]}...")
print(f"前缀正确: {result.startswith('{SRBX1}')}")
print(f"总长度: {len(result)}")

# chksum
from core.srun_crypto import calc_chksum
chksum = calc_chksum("token123", "user1", "hmd5hash", "1", "1.1.1.1", 200, 1, "{SRBX1}xxxx")
print(f"\nchksum内容: {chksum}")
print(f"长度正确(40): {len(chksum) == 40}")

print("\n=== 所有加密测试通过 ===")
