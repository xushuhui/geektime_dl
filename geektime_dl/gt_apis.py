# coding=utf8


import threading
import functools
import time
import contextlib
from typing import Optional

import requests

from geektime_dl.utils import (
    synchronized,
    Singleton,
    get_random_user_agent
)
from geektime_dl.log import logger


class GkApiError(Exception):
    """"""


def _retry(func):
    """
    0.1s 后重试
    """
    @functools.wraps(func)
    def wrap(gk_api: 'GkApiClient', *args, **kwargs):
        try:
            res = func(gk_api, *args, **kwargs)
            return res
        except requests.RequestException:
            time.sleep(0.1)
            gk_api.reset_session()
            return func(gk_api, *args, **kwargs)
        except GkApiError:
            raise
        except Exception as e:
            raise GkApiError("geektime api error") from e

    return wrap


class GkApiClient(metaclass=Singleton):
    """
    一个课程，包括专栏、视频、微课等，称作 `course` 或者 `column`
    课程下的章节，包括文章、者视频等，称作 `post` 或者 `article`
    """

    def __init__(self, account: str, password: str, area: str = '86',
                 no_login: bool = False, lazy_login: bool = True,
                 cookies: Optional[dict] = None):
        self._cookies = None
        self._lock = threading.Lock()
        self._account = account
        self._password = password
        self._area = area
        self._no_login = no_login
        self._ua = get_random_user_agent()

        if cookies:
            self._cookies = cookies
            return

        if lazy_login or no_login:
            return
        self.reset_session()

    def _post(self, url: str, data: dict = None, **kwargs) -> requests.Response:
        with contextlib.suppress(Exception):
            for k in ['cellphone', 'password']:
                if data and k in data:
                    data[k] = 'xxx'
            logger.info("request geektime api, {}, {}".format(url, data))

        headers = kwargs.setdefault('headers', {})
        headers.update({
            'Content-Type': 'application/json',
            'User-Agent': self._ua
        })
        resp = requests.post(url, json=data, timeout=10, **kwargs)
        resp.raise_for_status()

        if resp.json().get('code') != 0:
            raise GkApiError('geektime api fail:' + resp.json()['error']['msg'])

        return resp

    @synchronized()
    def reset_session(self) -> None:
        """登录"""
        url = 'https://account.geekbang.org/account/ticket/login'

        self._ua = get_random_user_agent()
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',  # noqa: E501
            'Host': 'account.geekbang.org',
            'Referer': 'https://account.geekbang.org/signin?redirect=https%3A%2F%2Fwww.geekbang.org%2F',  # noqa: E501
        }

        data = {
            "country": self._area,
            "cellphone": self._account,
            "password": self._password,
            "captcha": "",
            "remember": 1,
            "platform": 3,
            "appid": 1
        }

        resp = self._post(url, data, headers=headers)

        self._cookies = resp.cookies

    @_retry
    def get_course_list(self) -> dict:
        """
        获取课程列表
        :return:
            key: value
            '1'
            '2'
            '3'
            '4':
        """
        url = 'https://time.geekbang.org/serv/v1/column/all'
        headers = {
            'Referer': 'https://time.geekbang.org/paid-content',
        }
        if not self._cookies and not self._no_login:
            self.reset_session()

        resp = self._post(url, headers=headers, cookies=self._cookies)
        return resp.json()['data']

    @_retry
    def get_post_list_of(self, course_id: int) -> list:
        """获取课程所有章节列表"""
        url = 'https://time.geekbang.org/serv/v1/column/articles'
        data = {
            "cid": str(course_id), "size": 1000, "prev": 0, "order": "newest"
        }
        headers = {
            'Referer': 'https://time.geekbang.org/column/{}'.format(course_id),
        }

        if not self._cookies and not self._no_login:
            self.reset_session()

        resp = self._post(url, data, headers=headers, cookies=self._cookies)

        if not resp.json()['data']:
            raise Exception('course not exists:%s' % course_id)

        return resp.json()['data']['list'][::-1]

    @_retry
    def get_course_intro(self, course_id: int) -> dict:
        """课程简介"""
        url = 'https://time.geekbang.org/serv/v1/column/intro'
        headers = {
            'Referer': 'https://time.geekbang.org/column/{}'.format(course_id),
        }

        if not self._cookies and not self._no_login:
            self.reset_session()

        resp = self._post(
            url, {'cid': str(course_id)}, headers=headers, cookies=self._cookies
        )

        data = resp.json()['data']
        if not data:
            raise GkApiError('无效的课程 ID: {}'.format(course_id))
        return data

    @_retry
    def get_post_content(self, post_id: int) -> dict:
        """课程章节详情"""
        url = 'https://time.geekbang.org/serv/v1/article'
        headers = {
            'Referer': 'https://time.geekbang.org/column/article/{}'.format(
                post_id)
        }

        if not self._cookies and not self._no_login:
            self.reset_session()

        resp = self._post(
            url, {'id': post_id}, headers=headers, cookies=self._cookies
        )

        return resp.json()['data']

    @_retry
    def get_post_comments(self, post_id: int) -> list:
        """课程章节评论"""
        url = 'https://time.geekbang.org/serv/v1/comments'
        headers = {
            'Referer': 'https://time.geekbang.org/column/article/{}'.format(
                post_id)
        }

        if not self._cookies and not self._no_login:
            self.reset_session()
        arr = []
        prev = 0
        more = True
        while more == True:
            resp = self._post(
                url, {"aid": str(post_id), "prev": prev},
                headers=headers, cookies=self._cookies
            )
            data = resp.json()['data']
            list = data['list']
            arr.append(data['list'])
            more = data['page']['more']
            prev = list[len(list)-1]['score']
            
        return arr

    @_retry
    def get_video_collection_intro(self, collection_id: int) -> dict:
        """每日一课合辑简介"""
        url = 'https://time.geekbang.org/serv/v2/video/GetCollectById'
        headers = {
            'Referer': 'https://time.geekbang.org/dailylesson/collection/{}'.format(  # noqa: E501
                collection_id)
        }

        if not self._cookies and not self._no_login:
            self.reset_session()

        resp = self._post(
            url, {'id': str(collection_id)},
            headers=headers, cookies=self._cookies
        )

        data = resp.json()['data']
        return data

    @_retry
    def get_video_collection_list(self) -> list:
        """每日一课合辑列表"""
        # 没分析出接口
        ids = list(range(3, 82)) + list(range(104, 141))
        return [{'collection_id': id_} for id_ in ids]

    @_retry
    def get_video_list_of(self, collection_id: int) -> list:
        """每日一课合辑视频列表"""

        url = 'https://time.geekbang.org/serv/v2/video/GetListByType'
        headers = {
            'Referer': 'https://time.geekbang.org/dailylesson/collection/{}'.format(  # noqa: E501
                collection_id)
        }

        if not self._cookies and not self._no_login:
            self.reset_session()

        resp = self._post(
            url, {"id": str(collection_id), "size": 50},
            headers=headers, cookies=self._cookies
        )

        return resp.json()['data']['list']
if __name__=='__main__':
    get_post_comments(320569)