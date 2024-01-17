import json
import aiohttp
from data import config
from core.utils import web3_utils
from twocaptcha import TwoCaptcha


class Qna3:
    def __init__(self, key: str, use_bnb: bool = False):
        self.auth_token = self.recaptcha = self.user_id = None
        self.use_bnb = use_bnb
        self.web3_bnb_utils = web3_utils.Web3Utils(key=key, http_provider=config.BNB_RPC)
        self.web3_opbnb_utils = web3_utils.Web3Utils(key=key, http_provider=config.OPBNB_RPC)

        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'ua-UA,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'Host': 'api.qna3.ai',
            'Origin': 'https://qna3.ai',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'TE': 'trailers',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'x-lang': 'english',
        }

        self.session = aiohttp.ClientSession(headers=headers, trust_env=True)

    async def get_captcha_token(self, action: str = None):
        solver = TwoCaptcha(**{"apiKey": config.API_KEY_2CAPTCHA})

        params = {
            "sitekey": "6Lcq80spAAAAADGCu_fvSx3EG46UubsLeaXczBat",
            "url": "https://qna3.ai",
            "version": "v3",
            "enterprise": 1,
            'action': action
        }
        token = solver.recaptcha(**params)
        self.recaptcha = token['code']
        return token['code']

    async def login(self):
        address = self.web3_bnb_utils.acct.address
        signature = str(self.web3_bnb_utils.get_signed_code("AI + DYOR = Ultimate Answer to Unlock Web3 Universe"))
        captcha_token = await self.get_captcha_token()

        params = {
            'recaptcha': captcha_token,
            'invite_code': config.REF_CODE,
            'signature': signature,
            'wallet_address': address
        }

        resp = await self.session.post(url='https://api.qna3.ai/api/v2/auth/login?via=wallet', json=params)
        resp_txt = await resp.json()

        self.auth_token = 'Bearer ' + resp_txt.get('data').get('accessToken')
        self.user_id = resp_txt.get('data').get("user").get("id")

        self.session.headers['Authorization'] = self.auth_token
        self.session.headers['X-Id'] = self.user_id
        return True

    async def check_validate(self, tx_hash, via):
        captcha_token = await self.get_captcha_token(action='checkin')

        json_data = {
            'hash': tx_hash,
            'recaptcha': captcha_token,
            'via': via
        }

        resp = await self.session.post('https://api.qna3.ai/api/v2/my/validate', json=json_data)
        resp = await resp.json()
        return resp.get('statusCode') == 200

    async def claim_points(self, logger, thread):
        if not await self.check_today_claim():
            status, tx_hash = await self.send_claim_tx()
            if status:
                if await self.check_validate(tx_hash=tx_hash, via='bnb' if self.use_bnb else 'opbnb'):
                    resp_text = await self.send_claim_hash(tx_hash)
                    if resp_text == '{"statusCode":422,"message":"user already signed in today"}':
                        logger.warning(
                            f"Поток {thread} | Поинты с андреса {self.web3_opbnb_utils.acct.address}:{self.web3_opbnb_utils.acct.key.hex()} уже собраны")
                    elif json.loads(resp_text)['statusCode'] != 200:
                        logger.error(
                            f"Поток {thread} | Ошибка при отправке хэша на сайт с адреса {self.web3_opbnb_utils.acct.address}:{self.web3_opbnb_utils.acct.key.hex()}: {resp_text}")
                    else:
                        logger.success(
                            f"Поток {thread} | Успешно собрал поинты с адреса: {self.web3_opbnb_utils.acct.address}:{self.web3_opbnb_utils.acct.key.hex()}")
                else:
                    logger.error(f"Поток {thread} | Ошибка при валидации")
            else:
                logger.error(f"Поток {thread} | Ошибка при клейме: {tx_hash}")
        else:
            logger.warning(
                f"Поток {thread} | Сегодня уже клеймил поинты: {self.web3_opbnb_utils.acct.address}:{self.web3_opbnb_utils.acct.key.hex()}")

    async def check_today_claim(self):
        params = {
            "query": "query loadUserDetail($cursored: CursoredRequestInput!) {\n  userDetail {\n    checkInStatus {\n      checkInDays\n      todayCount\n    }\n    credit\n    creditHistories(cursored: $cursored) {\n      cursorInfo {\n        endCursor\n        hasNextPage\n      }\n      items {\n        claimed\n        extra\n        id\n        score\n        signDay\n        signInId\n        txHash\n        typ\n      }\n      total\n    }\n    invitation {\n      code\n      inviteeCount\n      leftCount\n    }\n    origin {\n      email\n      id\n      internalAddress\n      userWalletAddress\n    }\n    externalCredit\n    voteHistoryOfCurrentActivity {\n      created_at\n      query\n    }\n    ambassadorProgram {\n      bonus\n      claimed\n      family {\n        checkedInUsers\n        totalUsers\n      }\n    }\n  }\n}",
            "variables": {
                "cursored": {
                    "after": "",
                    "first": 20
                },
                "headersMapping": {
                    "Authorization": self.auth_token,
                    "x-id": self.user_id,
                    "x-lang": "english",
                }
            }
        }

        resp = await self.session.post(url='https://api.qna3.ai/api/v2/graphql', json=params)
        resp_txt = await resp.json()

        return resp_txt.get('data').get('userDetail').get('checkInStatus').get('todayCount')

    async def send_claim_tx(self):
        to = "0xB342e7D33b806544609370271A8D074313B7bc30"
        from_ = self.web3_bnb_utils.acct.address
        data = '0xe95a644f0000000000000000000000000000000000000000000000000000000000000001'
        gas_price = self.web3_bnb_utils.w3.to_wei('3', 'gwei') if self.use_bnb else self.web3_opbnb_utils.w3.to_wei('0.00002', 'gwei')
        gas_limit = 35000
        chain_id = 56 if self.use_bnb else 204

        if not self.use_bnb:
            return self.web3_opbnb_utils.send_data_tx(to=to, from_=from_, data=data, gas_price=gas_price, gas_limit=gas_limit, chain_id=chain_id)
        else:
            return self.web3_bnb_utils.send_data_tx(to=to, from_=from_, data=data, gas_price=gas_price, gas_limit=gas_limit, chain_id=chain_id)

    async def send_claim_hash(self, hash):
        params = {
            'recaptcha': self.recaptcha,
            'hash': hash,
            'via': 'bnb' if self.use_bnb else 'opbnb'
        }

        resp = await self.session.post(url='https://api.qna3.ai/api/v2/my/check-in', json=params)
        return await resp.text()

    async def logout(self):
        await self.session.close()
