"""
深澜 srun_portal 登录模块
完整登录流程：get_challenge → 加密 → 提交认证 → 在线检测
"""
import json
import logging
import time
import urllib.request
import urllib.parse
import re
from typing import Optional

from core.srun_crypto import (
    encode_srun_info, calc_hmd5, calc_chksum, calc_sha1
)

logger = logging.getLogger("CampusNet.Login")


class SrunLoginError(Exception):
    """登录异常"""
    pass


class SrunLogin:
    """深澜认证登录器"""

    def __init__(self, config: dict):
        self.config = config
        self.base_url = config["portal_url"].rstrip("/")
        self.username = config["username"]
        self.password = config["password"]
        self.ac_id = config.get("ac_id", "1")
        self._ip = None
        self._session = None

    def _get_session(self):
        """获取或创建 HTTP session"""
        if self._session is None:
            self._session = urllib.request.build_opener()
            self._session.addheaders = [
                ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
                ("Accept", "*/*"),
            ]
        return self._session

    def _do_request(self, url: str, params: dict = None, timeout: int = 10) -> Optional[str]:
        """发送 HTTP GET 请求"""
        try:
            if params:
                qs = urllib.parse.urlencode(params)
                full_url = f"{url}?{qs}"
            else:
                full_url = url

            req = urllib.request.Request(full_url)
            session = self._get_session()
            resp = session.open(req, timeout=timeout)
            data = resp.read().decode("utf-8", errors="replace")
            return data
        except Exception as e:
            logger.warning("HTTP 请求失败: %s - %s", url[:50], e)
            return None

    def _parse_jsonp(self, data: str) -> Optional[dict]:
        """解析 JSONP 响应为 dict"""
        if not data:
            return None
        try:
            # 提取 JSON 部分: callback(...) 或直接 JSON
            match = re.search(r"\{.*\}", data, re.DOTALL)
            if match:
                return json.loads(match.group())
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning("JSONP 解析失败: %s", e)
        return None

    def get_login_ip(self) -> str:
        """获取本机 IP：先从登录页面 CONFIG 获取，失败则从网卡获取"""
        if self._ip:
            return self._ip

        # 1. 从页面 CONFIG.ip 获取
        try:
            page_url = self.base_url + self.config["login_page"]
            html = self._do_request(page_url)
            if html:
                match = re.search(r'ip\s*:\s*"([^"]+)"', html)
                if match:
                    self._ip = match.group(1)
                    logger.info("从页面获取 IP: %s", self._ip)
                    return self._ip
        except Exception as e:
            logger.warning("获取页面 IP 失败: %s", e)

        # 2. 从网卡获取默认网关对应 IP
        try:
            import psutil, socket
            gateways = psutil.net_if_addrs()
            for name, addrs in gateways.items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                        self._ip = addr.address
                        logger.info("从网卡获取 IP: %s (%s)", self._ip, name)
                        return self._ip
        except Exception as e:
            logger.warning("网卡获取 IP 失败: %s", e)

        self._ip = "0.0.0.0"
        return self._ip

    def get_challenge(self) -> Optional[str]:
        """获取 challenge token"""
        callback = "jQuery" + str(int(time.time() * 1000))
        params = {
            "callback": callback,
            "username": self.username,
            "ip": self.get_login_ip()
        }
        url = self.base_url + "/cgi-bin/get_challenge"
        data = self._do_request(url, params)
        if not data:
            return None

        result = self._parse_jsonp(data)
        if result and "challenge" in result:
            return result["challenge"]
        logger.warning("get_challenge 返回异常: %s", str(result)[:100])
        return None

    def check_online(self) -> bool:
        """检查当前是否在线"""
        params = {"ip": self.get_login_ip()}
        url = self.base_url + "/cgi-bin/rad_user_info"
        data = self._do_request(url, params)
        if not data:
            return False
        result = self._parse_jsonp(data)
        # 在线时返回包含用户信息
        if result and "user_name" in result and result.get("user_name"):
            return True
        # 检查 suc_msg
        if result and result.get("suc_msg") == "success":
            return True
        return False

    def login(self) -> dict:
        """执行完整登录流程
        返回: {"success": bool, "message": str}
        """
        ip = self.get_login_ip()
        logger.info("开始登录流程, 用户: %s, IP: %s", self.username, ip)

        # Step 1: 获取 Challenge
        challenge = self.get_challenge()
        if not challenge:
            return {"success": False, "message": "获取 Challenge 失败"}

        logger.info("获取 Challenge 成功: %s...", challenge[:8])

        # Step 2: 计算 hmd5
        hmd5 = calc_hmd5(self.password, challenge)
        password_field = "{MD5}" + hmd5

        # Step 3: 编码用户信息
        info_dict = {
            "username": self.username,
            "password": self.password,
            "ip": ip,
            "acid": self.ac_id,
            "enc_ver": "srun_bx1"
        }
        info_enc = encode_srun_info(info_dict, challenge)

        # Step 4: 计算 chksum
        n = 200
        typ = 1
        chksum = calc_chksum(challenge, self.username, hmd5, self.ac_id,
                             ip, n, typ, info_enc)

        # Step 5: 提交登录
        callback = "jQuery" + str(int(time.time() * 1000))
        params = {
            "callback": callback,
            "action": "login",
            "username": self.username,
            "password": password_field,
            "ac_id": self.ac_id,
            "ip": ip,
            "chksum": chksum,
            "info": info_enc,
            "n": str(n),
            "type": str(typ),
            "os": "Windows 10",
            "name": "PC",
            "double_stack": "0",
        }

        url = self.base_url + "/cgi-bin/srun_portal"
        data = self._do_request(url, params)
        if not data:
            return {"success": False, "message": "登录请求无响应"}

        result = self._parse_jsonp(data)

        # Step 6: 判断结果
        if result is None:
            return {"success": False, "message": "解析登录响应失败"}

        # 成功
        if result.get("suc_msg") == "success":
            logger.info("登录成功!")
            return {"success": True, "message": "登录成功"}

        # 已在在线
        if result.get("error_msg") == "ip_already_online_error":
            logger.info("IP 已在线，无需登录")
            return {"success": True, "message": "IP 已在线"}

        # 其他错误
        error = result.get("error_msg") or result.get("error") or str(result)[:100]
        logger.warning("登录失败: %s", error)
        return {"success": False, "message": error}
