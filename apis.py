import re
import time
import random
import hashlib
import urllib.parse
import warnings

import lxml.etree
import execjs
import requests

class Tse:
    def __init__(self):
        self.author = 'Ulion.Tse'
        self.begin_time = time.time()
        self.default_session_seconds = 1.5e3

    @staticmethod
    def get_headers(host_url, if_api=False, if_referer_for_host=True, if_ajax_for_api=True, if_json_for_api=False):
        url_path = urllib.parse.urlparse(host_url).path
        user_agent = "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) " \
                     "Chrome/55.0.2883.87 Safari/537.36"
        host_headers = {
            'Referer' if if_referer_for_host else 'Host': host_url,
            "User-Agent": user_agent,
        }
        api_headers = {
            'Origin': host_url.split(url_path)[0] if url_path else host_url,
            'Referer': host_url,
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            "User-Agent": user_agent,
        }
        if if_api and not if_ajax_for_api:
            api_headers.pop('X-Requested-With')
            api_headers.update({'Content-Type': 'text/plain'})
        if if_api and if_json_for_api:
            api_headers.update({'Content-Type': 'application/json'})
        return host_headers if not if_api else api_headers

    @staticmethod
    def check_language(from_language, to_language, language_map, output_zh=None, output_auto='auto'):
        auto_pool = ('auto', 'auto-detect')
        zh_pool = ('zh', 'zh-CN', 'zh-CHS', 'zh-Hans', 'zh-Hans_CN', 'cn', 'chi')
        from_language = output_auto if from_language in auto_pool else from_language
        from_language = output_zh if output_zh and from_language in zh_pool else from_language
        to_language = output_zh if output_zh and to_language in zh_pool else to_language

        if from_language != output_auto and from_language not in language_map:
            raise TranslatorError('Unsupported from_language[{}] in {}.'.format(from_language, sorted(language_map.keys())))
        elif to_language not in language_map:
            raise TranslatorError('Unsupported to_language[{}] in {}.'.format(to_language, sorted(language_map.keys())))
        elif from_language != output_auto and to_language not in language_map[from_language]:
            raise TranslatorError('Unsupported translation: from [{0}] to [{1}]!'.format(from_language, to_language))
        return from_language, to_language

    @staticmethod
    def check_query_text(query_text, if_ignore_limit_of_length=False, limit_of_length=5000):
        if not isinstance(query_text, str):
            raise TranslatorError('query_text is not string type.')
        query_text = query_text.strip()
        length = len(query_text)
        if length >= limit_of_length and not if_ignore_limit_of_length:
            raise TranslatorError('The length of the text to be translated exceeds the limit.')
        else:
            if length >= limit_of_length:
                warnings.warn(
                    f'The translation ignored the excess[above {limit_of_length}]. Length of `query_text` is {length}.')
                warnings.warn('The translation result will be incomplete.')
                return query_text[:limit_of_length - 1]
        return query_text

class TranslatorError(Exception):
    pass

class Baidu(Tse):
    def __init__(self):
        super().__init__()
        self.host_url = 'https://fanyi.baidu.com'
        self.api_url = 'https://fanyi.baidu.com/v2transapi'
        self.langdetect_url = 'https://fanyi.baidu.com/langdetect'
        self.get_sign_old_url = 'https://fanyi-cdn.cdn.bcebos.com/static/translation/pkg/index_bd36cef.js'
        self.get_sign_url = None
        self.get_sign_pattern = 'https://fanyi-cdn.cdn.bcebos.com/static/translation/pkg/index_(.*?).js'
        self.host_headers = self.get_headers(self.host_url, if_api=False)
        self.api_headers = self.get_headers(self.host_url, if_api=True)
        self.language_map = None
        self.session = None
        self.professional_field = ('common', 'medicine', 'electronics', 'mechanics', 'novel')
        self.token = None
        self.sign = None
        self.query_count = 0
        self.output_zh = 'zh'
        self.input_limit = 5000

    def get_language_map(self, host_html, **kwargs):
        lang_str = re.compile('langMap: {(.*?)}').search(host_html.replace('\n', '').replace('  ', '')).group()[8:]
        return execjs.eval(lang_str)

    def get_sign(self, query_text, host_html, ss, timeout, proxies):
        gtk_list = re.compile("""window.gtk = '(.*?)';|window.gtk = "(.*?)";""").findall(host_html)[0]
        gtk = gtk_list[0] or gtk_list[1]

        try:
            if not self.get_sign_url:
                self.get_sign_url = re.compile(self.get_sign_pattern).search(host_html).group()
            r = ss.get(self.get_sign_url, headers=self.host_headers, timeout=timeout, proxies=proxies)
            r.raise_for_status()
        except:
            r = ss.get(self.get_sign_old_url, headers=self.host_headers, timeout=timeout, proxies=proxies)
            r.raise_for_status()
        sign_html = r.text

        begin_label = 'define("translation:widget/translate/input/pGrab",function(r,o,t){'
        end_label = 'var i=null;t.exports=e});'

        sign_js = sign_html[sign_html.find(begin_label) + len(begin_label):sign_html.find(end_label)]
        sign_js = sign_js.replace('function e(r)', 'function e(r,i)')
        return execjs.compile(sign_js).call('e', query_text, gtk)

    def get_tk(self, host_html):
        tk_list = re.compile("""token: '(.*?)',|token: "(.*?)",""").findall(host_html)[0]
        return tk_list[0] or tk_list[1]

    def baidu_api(self, query_text: str, from_language: str = 'auto', to_language: str = 'en', **kwargs):
        """
        https://fanyi.baidu.com
        :param query_text: str, must.
        :param from_language: str, default 'auto'.
        :param to_language: str, default 'en'.
        :param **kwargs:
                :param timeout: float, default None.
                :param proxies: dict, default None.
                :param sleep_seconds: float, default `random.random()`.
                :param is_detail_result: boolean, default False.
                :param if_ignore_limit_of_length: boolean, default False.
                :param limit_of_length: int, default 5000.
                :param if_ignore_empty_query: boolean, default False.
                :param update_session_after_seconds: float, default 1500.
                :param if_show_time_stat: boolean, default False.
                :param show_time_stat_precision: int, default 4.
                :param professional_field: str, default 'common'. Choose from ('common', 'medicine', 'electronics', 'mechanics', 'novel')
        :return: str or dict
        """

        timeout = kwargs.get('timeout', None)
        proxies = kwargs.get('proxies', None)
        is_detail_result = kwargs.get('is_detail_result', False)
        sleep_seconds = kwargs.get('sleep_seconds', random.random())
        update_session_after_seconds = kwargs.get('update_session_after_seconds', self.default_session_seconds)

        use_domain = kwargs.get('professional_field', 'common')
        if use_domain not in self.professional_field:  # only support zh-en, en-zh.
            raise TranslatorError

        not_update_cond_time = 1 if time.time() - self.begin_time < update_session_after_seconds else 0
        if not (self.session and not_update_cond_time and self.language_map and self.token and self.sign):
            self.session = requests.Session()
            _ = self.session.get(self.host_url, headers=self.host_headers, timeout=timeout, proxies=proxies)  # must twice, send cookies.
            host_html = self.session.get(self.host_url, headers=self.host_headers, timeout=timeout, proxies=proxies).text
            self.token = self.get_tk(host_html)
            self.sign = self.get_sign(query_text, host_html, self.session, timeout, proxies)
            self.language_map = self.get_language_map(host_html, from_language=from_language, to_language=to_language)

        from_language, to_language = self.check_language(from_language, to_language, self.language_map, output_zh=self.output_zh)
        if from_language == 'auto':
            res = self.session.post(self.langdetect_url, headers=self.api_headers, data={"query": query_text}, timeout=timeout, proxies=proxies)
            from_language = res.json()['lan']

        params = {"from": from_language, "to": to_language}
        form_data = {
            "from": from_language,
            "to": to_language,
            "query": query_text,  # from urllib.parse import quote_plus
            "transtype": "realtime",  # ["translang","realtime"]
            "simple_means_flag": "3",
            "sign": self.sign,
            "token": self.token,
            "domain": use_domain,
        }
        form_data = urllib.parse.urlencode(form_data).encode('utf-8')
        # self.api_headers.update({'Acs-Token': self.acs_token})
        r = self.session.post(self.api_url, params=params, data=form_data, headers=self.api_headers, timeout=timeout, proxies=proxies)
        r.raise_for_status()
        data = r.json()
        time.sleep(sleep_seconds)
        self.query_count += 1
        return data if is_detail_result else '\n'.join([x['dst'] for x in data['trans_result']['data']])

class Youdao(Tse):
    def __init__(self):
        super().__init__()
        self.host_url = 'https://fanyi.youdao.com'
        self.api_url = 'https://fanyi.youdao.com/translate_o?smartresult=dict&smartresult=rule'
        self.get_sign_old_url = 'https://shared.ydstatic.com/fanyi/newweb/v1.0.29/scripts/newweb/fanyi.min.js'
        self.get_sign_url = None
        self.get_sign_pattern = 'https://shared.ydstatic.com/fanyi/newweb/(.*?)/scripts/newweb/fanyi.min.js'
        self.host_headers = self.get_headers(self.host_url, if_api=False)
        self.api_headers = self.get_headers(self.host_url, if_api=True)
        self.language_map = None
        self.session = None
        self.sign_key = None
        self.query_count = 0
        self.output_zh = 'zh-CHS'
        self.input_limit = 5000

    def get_language_map(self, host_html, **kwargs):
        et = lxml.etree.HTML(host_html)
        lang_list = et.xpath('//*[@id="languageSelect"]/li/@data-value')
        print(lang_list)
        lang_list = [(x.split('2')[0], [x.split('2')[1]]) for x in lang_list if '2' in x]
        lang_map = dict(map(lambda x: x, lang_list))
        lang_map.pop('zh-CHS')
        lang_map.update({'zh-CHS': list(lang_map.keys())})
        return lang_map

    def get_sign_key(self, host_html, ss, timeout, proxies):
        try:
            if not self.get_sign_url:
                self.get_sign_url = re.compile(self.get_sign_pattern).search(host_html).group()
            r = ss.get(self.get_sign_url, headers=self.host_headers, timeout=timeout, proxies=proxies)
            r.raise_for_status()
        except:
            r = ss.get(self.get_sign_old_url, headers=self.host_headers, timeout=timeout, proxies=proxies)
            r.raise_for_status()
        sign = re.compile('md5\("fanyideskweb" \+ e \+ i \+ "(.*?)"\)').findall(r.text)
        return sign[0] if sign and sign != [''] else "Ygy_4c=r#e#4EX^NUGUc5"  # v1.1.10

    def get_form(self, query_text, from_language, to_language, sign_key):
        ts = str(int(time.time() * 1000))
        salt = str(ts) + str(random.randrange(0, 10))
        sign_text = ''.join(['fanyideskweb', query_text, salt, sign_key])
        sign = hashlib.md5(sign_text.encode()).hexdigest()
        bv = hashlib.md5(self.api_headers['User-Agent'][8:].encode()).hexdigest()
        form = {
            'i': query_text,
            'from': from_language,
            'to': to_language,
            'lts': ts,  # r = "" + (new Date).getTime()
            'salt': salt,  # i = r + parseInt(10 * Math.random(), 10)
            'sign': sign,  # n.md5("fanyideskweb" + e + i + "n%A-rKaT5fb[Gy?;N5@Tj"),e=text
            'bv': bv,  # n.md5(navigator.appVersion)
            'smartresult': 'dict',
            'client': 'fanyideskweb',
            'doctype': 'json',
            'version': '2.1',
            'keyfrom': 'fanyi.web',
            'action': 'FY_BY_REALTlME',  # not time.["FY_BY_REALTlME", "FY_BY_DEFAULT", "FY_BY_CLICKBUTTION", "lan-select"]
            # 'typoResult': 'false'
        }
        return form

    def youdao_api(self, query_text: str, from_language: str = 'auto', to_language: str = 'en', **kwargs):
        timeout = kwargs.get('timeout', None)
        proxies = kwargs.get('proxies', None)
        is_detail_result = kwargs.get('is_detail_result', False)
        sleep_seconds = kwargs.get('sleep_seconds', random.random())
        update_session_after_seconds = kwargs.get('update_session_after_seconds', self.default_session_seconds)

        not_update_cond_time = 1 if time.time() - self.begin_time < update_session_after_seconds else 0
        if not (self.session and not_update_cond_time and self.language_map and self.sign_key):
            self.session = requests.Session()
            host_html = self.session.get(self.host_url, headers=self.host_headers, timeout=timeout, proxies=proxies).text
            self.sign_key = self.get_sign_key(host_html, self.session, timeout, proxies)

        form = self.get_form(query_text, from_language, to_language, self.sign_key)
        r = self.session.post(self.api_url, data=form, headers=self.api_headers, timeout=timeout, proxies=proxies)
        r.raise_for_status()
        data = r.json()
        time.sleep(sleep_seconds)
        self.query_count += 1
        return data if is_detail_result else '\n'.join([' '.join([it['tgt'] for it in item]) for item in data['translateResult']])

_baidu = Baidu()
baidu = _baidu.baidu_api
_youdao = Youdao()
youdao = _youdao.youdao_api