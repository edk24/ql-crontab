#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
丝路国际签到打卡脚本
环境变量配置：
SLGJ_USER: phone=手机号&password=密码
cron: 0,10 9 * * *

说明：
  - 脚本通过一个环境变量`SLGJ_USER`获取账号信息。
  - 格式为`phone=手机号&password=密码`，会自动拆解为手机号码和密码。
  - 兼容`YH_USERNAME`/`YH_PASSWORD`将不再使用。
"""
import os
import sys
import json
import time
import random
import logging
import requests
import urllib3
from typing import Dict, Any, Optional, List
from datetime import datetime

# 禁用SSL警告和urllib3的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import warnings
warnings.filterwarnings('ignore')

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('YHCheckIn')

# 通知推送函数（青龙面板环境）
def send_notification(title: str, content: str):
    """发送通知"""
    try:
        # 尝试导入青龙面板的通知模块
        try:
            from notify import send as ql_send
            ql_send(f"{title}", content)
            logger.info(f"已通过青龙通知发送: {title}")
            return
        except ImportError:
            pass
        
        # 检查青龙面板环境变量
        env_vars = {
            'PUSH_PLUS_TOKEN': 'pushplus',
            'BARK_PUSH': 'bark',
            'TG_BOT_TOKEN': 'telegram',
            'DD_BOT_TOKEN': '钉钉',
            'FSKEY': '飞书'
        }
        
        # 输出到日志，青龙面板会捕获
        logger.info(f"【{title}】{content}")
        
        # 如果青龙面板有通知配置，这里可以添加推送逻辑
        for env_var, platform in env_vars.items():
            if os.environ.get(env_var):
                logger.info(f"检测到{platform}通知配置，可在此处实现推送")
                
    except Exception as e:
        logger.error(f"发送通知失败: {e}")

class YHCheckIn:
    def __init__(self):
        # 获取环境变量并解析 (仅支持 SLGJ_USER)
        user_env = os.environ.get('SLGJ_USER', '').strip()
        self.username = ''
        self.password = ''
        if user_env:
            try:
                parts = dict(item.split('=', 1) for item in user_env.split('&') if '=' in item)
                self.username = parts.get('phone', '').strip()
                self.password = parts.get('password', '').strip()
            except Exception:
                logger.warning(f"无法解析 SLGJ_USER: {user_env}")
        
        if not self.username or not self.password:
            error_msg = (
                "错误: 请设置环境变量 SLGJ_USER，格式 'phone=手机号&password=密码'"
            )
            logger.error(error_msg)
            send_notification("签到失败", error_msg)
            sys.exit(1)
        
        logger.info(f"初始化签到脚本，用户: {self.username[:3]}****{self.username[-4:]}")
        
        # 初始化session
        self.session = requests.Session()
        
        # 默认请求头
        self.base_headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Html5Plus/1.0 (Immersed/59) uni-app',
            'Accept-Language': 'zh-CN,zh-Hans;q=0.9',
            'appVersion': '1.0.2.0',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept': '*/*',
            'Connection': 'keep-alive'
        }
        
        self.base_url = ""
        self.user_info = {}
        self.token = ""
        self.domain_list = []
        self.balance_info = {}  # 存储余额信息
        
    def _is_domain_alive(self, domain: str) -> bool:
        """简单检测给定域名是否可用"""
        try:
            # 测试登录接口是否响应（不带有效数据）
            test_url = domain.rstrip('/') + "/app/sn-personal/insurance/user/login"
            resp = self.session.options(
                test_url,
                headers=self.base_headers,
                timeout=5,
                verify=False
            )
            # 只要不是服务器错误即可认为可用
            return resp.status_code < 500
        except Exception:
            return False

    def get_random_domain(self) -> str:
        """获取随机且可用的域名"""
        logger.info("开始获取可用域名...")
        timestamp = int(time.time() * 1000)
        url = f"https://silugj-1322772389.cos.accelerate.myqcloud.com/yydsslgj.json?t={timestamp}"
        logger.debug(f"请求域名接口: {url}")
        try:
            response = self.session.get(
                url,
                headers=self.base_headers,
                timeout=10,
                verify=False
            )
            logger.info(f"域名接口响应状态: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                logger.debug(f"域名接口返回数据: {json.dumps(data, ensure_ascii=False)}")
                key_list = data.get('keyList', '')
                if key_list:
                    self.domain_list = [d.strip() for d in key_list.split(',') if d.strip()]
                    logger.info(f"成功获取域名列表: {self.domain_list}")
            else:
                logger.warning(f"域名接口请求失败: HTTP {response.status_code}")
                logger.debug(f"响应内容: {response.text}")
        except requests.exceptions.Timeout:
            logger.error("获取域名请求超时")
        except requests.exceptions.ConnectionError:
            logger.error("获取域名连接错误")
        except Exception as e:
            logger.error(f"获取域名过程异常: {str(e)}", exc_info=True)

        # 从列表中挑选第一个可用的域名
        random.shuffle(self.domain_list)
        for dom in self.domain_list:
            if self._is_domain_alive(dom):
                logger.info(f"选择可用域名: {dom}")
                return dom
            else:
                logger.warning(f"域名不可用，跳过: {dom}")

        # 如果所有获取的域名不可用，则使用备用域名并验证
        backup_domains = [
            "https://api.ockw6.com",
            "https://api.skw68.com",
            "https://api.yinhehapi.com"
        ]
        logger.info(f"尝试备用域名列表: {backup_domains}")
        random.shuffle(backup_domains)
        for dom in backup_domains:
            if self._is_domain_alive(dom):
                logger.info(f"备用域名可用: {dom}")
                return dom
            else:
                logger.warning(f"备用域名不可用: {dom}")

        # 最后一手段，返回第一个原始域名或备选
        fallback = self.domain_list[0] if self.domain_list else backup_domains[0]
        logger.warning(f"未找到可用域名，使用回退: {fallback}")
        return fallback
    
    def login(self) -> bool:
        """登录账号"""
        try:
            if not self.base_url:
                self.base_url = self.get_random_domain()
                logger.info(f"最终使用域名: {self.base_url}")
            
            login_url = f"{self.base_url}/app/sn-personal/insurance/user/login"
            logger.info(f"登录URL: {login_url}")
            
            # 准备登录数据
            login_data = {
                "phonenumber": self.username,
                "password": self.password,
                "phoneNumber": self.username
            }
            
            logger.debug(f"登录请求数据: {json.dumps(login_data, ensure_ascii=False)}")
            
            # 设置请求头
            headers = self.base_headers.copy()
            host = self.base_url.replace('https://', '').replace('http://', '')
            headers.update({
                'Host': host,
                'Content-Type': 'application/json',
                'Cookie': 'JSESSIONID=FA0FA16716FE4162128CB2ADF1CF5602'
            })
            
            logger.debug(f"登录请求头: {json.dumps({k: v for k, v in headers.items() if k not in ['Cookie', 'Accept-Encoding']}, ensure_ascii=False)}")
            
            start_time = time.time()
            response = self.session.post(
                login_url,
                headers=headers,
                json=login_data,
                timeout=15,
                verify=False
            )
            request_time = time.time() - start_time
            
            logger.info(f"登录请求耗时: {request_time:.2f}秒")
            logger.info(f"登录响应状态: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    logger.debug(f"登录响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
                    
                    code = result.get('code')
                    message = result.get('message', '无消息')
                    
                    if code == 200:
                        data = result.get('data', {})
                        
                        self.user_info = {
                            'userId': data.get('userId'),
                            'nickName': data.get('nickName'),
                            'inviteUserId': data.get('inviteUserId')
                        }
                        
                        self.token = data.get('token', '')
                        
                        if self.token:
                            logger.info("=" * 50)
                            logger.info("登录成功!")
                            logger.info(f"用户ID: {self.user_info['userId']}")
                            logger.info(f"昵称: {self.user_info['nickName']}")
                            logger.info(f"邀请用户ID: {self.user_info['inviteUserId']}")
                            logger.info(f"Token: {self.token[:20]}...")
                            logger.info("=" * 50)
                            return True
                        else:
                            logger.error("登录失败: 未获取到token")
                    else:
                        logger.error(f"登录失败: 代码={code}, 消息={message}")
                except json.JSONDecodeError as e:
                    logger.error(f"解析登录响应JSON失败: {e}")
                    logger.debug(f"响应内容: {response.text}")
            else:
                logger.error(f"登录请求失败: HTTP {response.status_code}")
                logger.debug(f"响应内容: {response.text}")
                
            return False
            
        except requests.exceptions.Timeout:
            logger.error("登录请求超时")
        except requests.exceptions.ConnectionError:
            logger.error("登录连接错误")
        except Exception as e:
            logger.error(f"登录过程异常: {str(e)}", exc_info=True)
        return False
    
    def get_user_wallet_balance(self) -> Dict[str, Any]:
        """获取用户钱包余额"""
        try:
            if not self.token:
                logger.error("错误: 请先登录获取token")
                return {}
            
            wallet_url = f"{self.base_url}/app/sn-personal/insurance/user-wallet/getUserWallet"
            logger.info(f"获取余额URL: {wallet_url}")
            
            # 设置带token的请求头
            headers = self.base_headers.copy()
            host = self.base_url.replace('https://', '').replace('http://', '')
            headers.update({
                'access-token': self.token,
                'Host': host,
                'Content-Type': 'application/json'
            })
            
            logger.debug(f"余额请求头: {json.dumps({k: v for k, v in headers.items() if k != 'access-token'}, ensure_ascii=False)}")
            logger.debug(f"余额Token: {self.token[:20]}...")
            
            # 准备请求数据（可能需要根据实际接口调整）
            wallet_data = {}
            
            logger.debug(f"余额请求数据: {json.dumps(wallet_data, ensure_ascii=False)}")
            
            start_time = time.time()
            response = self.session.post(
                wallet_url,
                headers=headers,
                json=wallet_data,
                timeout=15,
                verify=False
            )
            request_time = time.time() - start_time
            
            logger.info(f"余额请求耗时: {request_time:.2f}秒")
            logger.info(f"余额响应状态: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    logger.debug(f"余额响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
                    
                    code = result.get('code')
                    message = result.get('message', '无消息')
                    
                    if code == 200:
                        data = result.get('data', {})
                        
                        # 提取余额信息
                        cny_withdrawable_balance = data.get('cnyWithdrawableBalance', 0)
                        
                        self.balance_info = {
                            'cnyWithdrawableBalance': cny_withdrawable_balance,  # 可提现余额
                            'unit': 'CNY'                                        # 货币单位
                        }
                        
                        # 格式化输出余额信息
                        logger.info("=" * 50)
                        logger.info("💰 钱包余额信息:")
                        logger.info(f"  可提现余额: ¥{cny_withdrawable_balance:.2f}")
                        
                        logger.info("=" * 50)
                        
                        return self.balance_info
                    else:
                        logger.warning(f"获取余额失败: 代码={code}, 消息={message}")
                        
                except json.JSONDecodeError as e:
                    logger.error(f"解析余额响应JSON失败: {e}")
                    logger.debug(f"响应内容: {response.text}")
            else:
                logger.warning(f"余额请求失败: HTTP {response.status_code}")
                logger.debug(f"响应内容: {response.text}")
                
        except requests.exceptions.Timeout:
            logger.warning("获取余额请求超时")
        except requests.exceptions.ConnectionError:
            logger.warning("获取余额连接错误")
        except Exception as e:
            logger.warning(f"获取余额过程异常: {str(e)}", exc_info=True)
        
        return {}
    
    def check_in(self) -> bool:
        """打卡签到"""
        try:
            if not self.token:
                logger.error("错误: 请先登录获取token")
                return False
            
            checkin_url = f"{self.base_url}/app/sn-personal/insurance/user/sign-in/insert"
            logger.info(f"签到URL: {checkin_url}")
            
            # 设置带token的请求头
            headers = self.base_headers.copy()
            host = self.base_url.replace('https://', '').replace('http://', '')
            headers.update({
                'access-token': self.token,
                'Host': host,
                'Content-Type': 'application/json'
            })
            
            logger.debug(f"签到请求头: {json.dumps({k: v for k, v in headers.items() if k != 'access-token'}, ensure_ascii=False)}")
            logger.debug(f"签到Token: {self.token[:20]}...")
            
            # 签到请求数据（根据实际接口可能需要调整）
            checkin_data = {
                # 根据实际接口需要添加参数，目前为空
            }
            
            logger.debug(f"签到请求数据: {json.dumps(checkin_data, ensure_ascii=False)}")
            
            start_time = time.time()
            response = self.session.post(
                checkin_url,
                headers=headers,
                json=checkin_data,
                timeout=15,
                verify=False
            )
            request_time = time.time() - start_time
            
            logger.info(f"签到请求耗时: {request_time:.2f}秒")
            logger.info(f"签到响应状态: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    logger.debug(f"签到响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
                    
                    code = result.get('code')
                    message = result.get('message', '无消息')
                    
                    if code == 200:
                        # 尝试获取更多签到信息
                        data = result.get('data', {})
                        if isinstance(data, dict):
                            sign_info = []
                            for key, value in data.items():
                                if value is not None:
                                    sign_info.append(f"{key}: {value}")
                            
                            if sign_info:
                                detail_msg = f"{message}\n详情: {'; '.join(sign_info)}"
                            else:
                                detail_msg = message
                        else:
                            detail_msg = f"{message} (返回数据: {data})"
                        
                        logger.info("=" * 50)
                        logger.info(f"🎉 签到成功!")
                        logger.info(f"📝 消息: {detail_msg}")
                        
                        # 签到后重新获取余额，看是否有变化
                        old_balance = self.balance_info.get('cnyWithdrawableBalance', 0)
                        new_balance_info = self.get_user_wallet_balance()
                        new_balance = new_balance_info.get('cnyWithdrawableBalance', 0)
                        
                        if new_balance > old_balance:
                            increase = new_balance - old_balance
                            logger.info(f"💰 余额增加: ¥{increase:.2f}")
                            logger.info(f"💰 当前可提现余额: ¥{new_balance:.2f}")
                        
                        logger.info("=" * 50)
                        
                        # 发送通知
                        notification_content = (
                            f"用户: {self.user_info.get('nickName', '未知')}\n"
                            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"结果: {detail_msg}\n"
                            f"当前余额: ¥{new_balance:.2f}\n"
                            f"域名: {self.base_url}"
                        )
                        
                        if new_balance > old_balance:
                            notification_content += f"\n🎊 本次增加: ¥{increase:.2f}"
                        
                        send_notification("🎉 签到成功", notification_content)
                        return True
                    else:
                        logger.error(f"签到失败: 代码={code}, 消息={message}")
                        
                        # 发送失败通知
                        send_notification(
                            "❌ 签到失败",
                            f"用户: {self.user_info.get('nickName', '未知')}\n"
                            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"原因: {message} (代码: {code})\n"
                            f"当前余额: ¥{self.balance_info.get('cnyWithdrawableBalance', 0):.2f}"
                        )
                except json.JSONDecodeError as e:
                    logger.error(f"解析签到响应JSON失败: {e}")
                    logger.debug(f"响应内容: {response.text}")
                    send_notification("❌ 签到异常", f"解析响应失败: {e}")
            else:
                error_msg = f"签到请求失败: HTTP {response.status_code}"
                logger.error(error_msg)
                logger.debug(f"响应内容: {response.text}")
                send_notification("❌ 签到失败", error_msg)
                
            return False
            
        except requests.exceptions.Timeout:
            logger.error("签到请求超时")
            send_notification("❌ 签到超时", "请求超时，请稍后重试")
        except requests.exceptions.ConnectionError:
            logger.error("签到连接错误")
            send_notification("❌ 连接错误", "网络连接失败")
        except Exception as e:
            error_msg = f"签到过程异常: {str(e)}"
            logger.error(error_msg, exc_info=True)
            send_notification("❌ 签到异常", error_msg)
        return False
    
    def run(self):
        """执行签到流程"""
        print("=" * 70)
        logger.info(f"开始处理账号: {self.username[:3]}****{self.username[-4:]}")
        logger.info(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        # 步骤1: 登录
        logger.info("\n" + "📱" * 10 + " 开始登录 " + "📱" * 10)
        if not self.login():
            send_notification("❌ 签到失败", "登录失败，请检查账号密码或网络")
            return
        
        # 步骤2: 获取签到前的余额
        logger.info("\n" + "💰" * 10 + " 获取签到前余额 " + "💰" * 10)
        self.get_user_wallet_balance()
        
        # 步骤3: 签到
        logger.info("\n" + "✅" * 10 + " 开始签到 " + "✅" * 10)
        success = self.check_in()
        
        print("\n" + "=" * 70)
        if success:
            logger.info("🎉 签到流程完成 - 成功 🎉")
        else:
            logger.info("❌ 签到流程完成 - 失败 ❌")
        print("=" * 70)
        
        # 输出总结信息
        logger.info(f"\n📊 执行总结:")
        logger.info(f"  账号: {self.username[:3]}****{self.username[-4:]}")
        logger.info(f"  昵称: {self.user_info.get('nickName', '未知')}")
        logger.info(f"  使用域名: {self.base_url}")
        logger.info(f"  当前可提现余额: ¥{self.balance_info.get('cnyWithdrawableBalance', 0):.2f}")
        logger.info(f"  执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  签到结果: {'成功' if success else '失败'}")

def main():
    """主函数"""
    try:
        # 检查环境变量
        if 'SLGJ_USER' not in os.environ:
            logger.warning("=" * 60)
            logger.warning("⚠️  提示: 请在青龙面板环境变量中设置:")
            logger.warning("    SLGJ_USER: phone=手机号&password=密码")
            logger.warning("=" * 60)
            
            # 测试用，正式使用请注释掉
            # os.environ['SLGJ_USER'] = 'phone=1831***48014&password=Sl***678'
            
            send_notification("配置错误", "请设置环境变量 SLGJ_USER")
            sys.exit(1)
        
        # 创建实例并运行
        checker = YHCheckIn()
        checker.run()
        
    except KeyboardInterrupt:
        logger.info("\n用户中断执行")
        send_notification("脚本中断", "用户手动中断执行")
    except Exception as e:
        logger.error(f"程序执行异常: {str(e)}", exc_info=True)
        send_notification("脚本异常", f"程序异常: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()