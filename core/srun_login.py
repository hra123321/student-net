"""
深澜 srun_portal 登录模块
完整登录流程：get_challenge -> 加密 -> 提交认证 -> 在线检测
"""
import json
import logging
import re
import time
import urllib.request
import urllib.parse
from typing import Optional

from core.srun_crypto import encode_srun_info, calc_hmd5, calc_chksum

logger = logging.getLogger("CampusNet.Login")


class SrunLogin:
    """深澜认证登录器"""

    def __init__(self, config: dict, network_monitor=None):
        self.config = config
        self.base_url = config["portal_url"].rstrip("/")
        self.username = config["username"]
        self.password = config["password"]
        self.ac_id = config.get("ac_id", "")
        self._ip = None
        self._opener = None
        self.network_monitor = network_monitor

    def _get_opener(self):
        if self._opener is None:
            import http.cookiejar
            cj = http.cookiejar.CookieJar()
            self._opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(cj))
            self._opener.addheaders = [
                ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
            ]
        return self._opener

    def _fetch_page_config(self):
        """从登录页提取 CONFIG（IP 和 ac_id）"""
        try:
            opener = self._get_opener()
            url = self.base_url + self.config["login_page"]
            resp = opener.open(url, timeout=10)
            html = resp.read().decode("utf-8", errors="replace")

            ip_m = re.search(r'ip\s*:\s*"([^"]*)"', html)
            acid_m = re.search(r'acid\s*:\s*"([^"]*)"', html)
            if ip_m: self._ip = ip_m.group(1)
            if acid_m and acid_m.group(1): self.ac_id = acid_m.group(1)
            logger.info("页面配置: IP=%s, ac_id=%s", self._ip, self.ac_id)
        except Exception as e:
            logger.warning("获取页面配置失败: %s", e)

    def _do_request(self, url: str, params: dict = None, timeout: int = 10) -> Optional[str]:
        try:
            if params:
                qs = urllib.parse.urlencode(params)
                full_url = f"{url}?{qs}"
            else:
                full_url = url
            opener = self._get_opener()
            resp = opener.open(full_url, timeout=timeout)
            return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning("HTTP 请求失败: %s", e)
            return None

    def _parse_jsonp(self, data: str) -> Optional[dict]:
        if not data: return None
        try:
            m = re.search(r"\{.*\}", data, re.DOTALL)
            return json.loads(m.group()) if m else None
        except (json.JSONDecodeError, AttributeError):
            return None

    def get_login_ip(self) -> str:
        if self._ip: return self._ip
        self._fetch_page_config()
        if not self._ip:
            try:
                if self.network_monitor:
                    active = self.network_monitor.get_active_interface()
                    if active.get("ipv4"):
                        self._ip = active["ipv4"]
                        return self._ip
                import psutil, socket
                for name, addrs in psutil.net_if_addrs().items():
                    for addr in addrs:
                        if addr.family == socket.AF_INET and not addr.address.startswith("127.") and not addr.address.startswith("169."):
                            self._ip = addr.address
                            return self._ip
            except: pass
        self._ip = self._ip or "0.0.0.0"
        return self._ip

    def get_challenge(self) -> Optional[str]:
        cb = "jQuery" + str(int(time.time() * 1000000))
        data = self._do_request(
            self.base_url + "/cgi-bin/get_challenge",
            {"callback": cb, "username": self.username, "ip": self.get_login_ip()})
        if not data: return None
        r = self._parse_jsonp(data)
        return r.get("challenge") if r else None

    def check_online(self, retry: bool = False) -> bool:
        """检查是否在线，支持自动重试（登录成功后 rad_user_info 有延迟）"""
        if retry:
            for attempt in range(5):
                result = self._check_online_once()
                if result:
                    return True
                time.sleep(1)
            return False
        return self._check_online_once()

    def _check_online_once(self) -> bool:
        data = self._do_request(
            self.base_url + "/cgi-bin/rad_user_info",
            {"ip": self.get_login_ip()})
        if not data:
            return False
        r = self._parse_jsonp(data)
        if r:
            return bool(r.get("user_name") or r.get("online_ip") or r.get("client_ip"))

        # Some srun versions return CSV: username,...,ip,...
        parts = [part.strip() for part in data.strip().split(",")]
        if len(parts) >= 9:
            return bool(parts[0] and parts[8] == self.get_login_ip())
        return False

    def login(self) -> dict:
        """完整登录流程"""
        ip = self.get_login_ip()
        logger.info("登录: user=%s ip=%s", self.username, ip)

        challenge = self.get_challenge()
        if not challenge:
            return {"success": False, "message": "获取 Challenge 失败"}
        logger.debug("Challenge: %s...", challenge[:8])

        hmd5 = calc_hmd5(self.password, challenge)
        info = {"username": self.username, "password": self.password,
                "ip": ip, "acid": self.ac_id, "enc_ver": "srun_bx1"}
        info_enc = encode_srun_info(info, challenge)
        chksum = calc_chksum(challenge, self.username, hmd5, self.ac_id,
                             ip, 200, 1, info_enc)

        cb = "jQuery" + str(int(time.time() * 1000000))
        data = self._do_request(
            self.base_url + "/cgi-bin/srun_portal",
            {"callback": cb, "action": "login", "username": self.username,
             "password": "{MD5}" + hmd5, "ac_id": self.ac_id, "ip": ip,
             "chksum": chksum, "info": info_enc, "n": "200", "type": "1",
             "os": "Windows 10", "name": "PC", "double_stack": "0"})

        if not data:
            return {"success": False, "message": "登录无响应"}

        r = self._parse_jsonp(data)
        if not r:
            return {"success": False, "message": "解析响应失败"}

        if r.get("error") == "ok" or r.get("suc_msg") == "success":
            logger.info("登录成功!")
            # 登录成功后等待并确认在线状态
            time.sleep(2)
            self.check_online(retry=True)
            return {"success": True, "message": "登录成功"}

        already_online = {r.get("error"), r.get("error_msg"), r.get("res")}
        if "ip_already_online_error" in already_online:
            logger.info("IP already online")
            return {"success": True, "message": "IP already online"}

        err = r.get("error") or r.get("error_msg") or str(r)[:100]
        logger.warning("登录失败: %s", err)
        return {"success": False, "message": err}
