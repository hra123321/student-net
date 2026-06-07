# 深澜 srun_portal 协议逆向文档

## 基本信息
- 门户系统: 深澜软件 SRun Portal
- 版本: 2.00.20231007
- 服务端: Go语言实现 (SRunFlag: "SRun portal server golang version")
- Web服务器: nginx

## 登录流程

### Step 1: 获取 Challenge Token
```
GET /cgi-bin/get_challenge
参数:
  callback: jQuery{timestamp}
  username: {用户名}
  ip: {本机IP}
返回: {challenge: "随机32位hex字符串"}
```

### Step 2: 计算密码摘要
```
hmd5 = HMAC-MD5(key=challenge, data=password).hex()
password_field = "{MD5}" + hmd5
```

### Step 3: 编码用户信息 ({SRBX1})
```
info_json = JSON.stringify({
    username: username,
    password: password,
    ip: ip,
    acid: ac_id,
    enc_ver: "srun_bx1"
})

加密流程:
1. XXTEA 加密 (key=challenge token)
   - delta = 0x9E3779B9 (标准XXTEA)
   - 输入字符串转为32位小端序整数数组
   - 执行Corrected Block TEA加密
   - 结果转回字节串
2. 自定义Base64编码
   - 字母表: "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"
3. 添加前缀: "{SRBX1}" + 编码结果
```

### Step 4: 计算校验和
```
chksum_str = challenge + username + challenge + hmd5 + challenge + ac_id
           + challenge + ip + challenge + str(n) + challenge + str(type)
           + challenge + info_encoded
chksum = SHA1(chksum_str).hex()
```

### Step 5: 提交登录
```
GET /cgi-bin/srun_portal
参数:
  action: login
  username: {用户名}
  password: {MD5}{hmd5}
  ac_id: {ac_id}
  ip: {本机IP}
  chksum: {SHA1校验和}
  info: {SRBX1}{编码信息}
  n: 200
  type: 1
  os: "Windows 10"
  name: "PC"
  double_stack: 0
```

### Step 6: 判断结果
成功: {suc_msg: "success"}
已在线: {error_msg: "ip_already_online_error"}
失败: {error_msg: "错误说明"}

## 其他API
- 在线检测: GET /cgi-bin/rad_user_info?ip={ip}
- 注销: GET /cgi-bin/srun_portal?action=logout
- 在线设备管理: GET /v1/srun_portal_online

## 常量
n = 200
type = 1
enc_ver = "srun_bx1"
