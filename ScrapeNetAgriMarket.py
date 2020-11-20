import json
import time
import os

import requests
from selenium import webdriver
from selenium.webdriver.support.select import Select
import pandas as pd

SLACK_WEBHOOK_URL = os.environ['SLACK_WEBHOOK_URL']
USER_INFO_ID = os.environ['USER_INFO_ID']
USER_INFO_PW = os.environ['USER_INFO_PW']
READ_CODE = os.environ['READ_CODE']

LOGIN_PAGE_URL = 'https://www.agrishikyo.jp/LOGIN2017/CGI/LOGIN2017TOP.CGI'

keywords_list1 = ['ジャガイモ', 'ナガイモ']  # 気配値(quote_prices)用
keywords_list2 = ['ジャガイモ', 'ヤマノイモ']  # キロ単価(unit_prices)用


def format_date(shikyo_date):
    # 取引日「2020年11月09日の取引」を数字8桁「20201109」に整形する関数
    return shikyo_date[:-3].replace('年', '').replace('月', '').replace('日', '')


def scrape_unit_prices(browser, keywords_list):
    """「キロ単価」のデータを取得してdfに格納する関数
    Args:
        browser(selenium.WebBowser)
        keywords_list(list): スクレイピングする品目名リスト
    Return:
        pandas.DataFrame: 品目名リストについて取得したキロ単価のデータフレーム"""
    # 2-1.スクレイピングしたい市況データ表を表示
    # - 青果＞１キロ平均価格（確定値）＞品物別で「ジャガイモ」「ヤマノイモ」

    # メニューから「青果」の「１キロ平均価格（確定値）」をクリックしてページに飛ぶ
    browser.execute_script("gotoURL('/SEIKA_KAKUTEI2012/CGI/SEIKA_KAKUTEI.CGI')")
    # 「品目別で選択（クリック）」
    browser.execute_script("changeView('HINMOKU')")
    # 品目を選択
    item_list = Select(browser.find_element_by_css_selector('#hinmoku_select > select'))

    # 2-2. 市況データを取得してリスト・データフレームとして保持する
    # - １キロ平均価格の「札幌市」「東京都」「大阪市」のみの六日間の数値を取得する

    dfs_trade_data = []  # 品目ごとのデータフレームを保持

    for keyword in keywords_list:
        item_list.select_by_visible_text(keyword)

        tables = browser.find_elements_by_tag_name('table')

        item_name = browser.find_element_by_css_selector('#main_table > div:nth-child(3) > div:nth-child(1)').text  # 品目名
        shikyo_date = tables[2].text  # 取引日の文字列
        shikyo_headers = tables[3].find_elements_by_tag_name('th')  # カラム名の入ったWebElementオブジェクトのリスト
        shikyo_data = tables[4].find_elements_by_tag_name('td')  # 取引データの入ったWebElementオブジェクトのリスト

        # 取引日
        trade_date = format_date(shikyo_date)

        # ヘッダーを準備
        trade_headers = [element.text for element in shikyo_headers]
        trade_headers = trade_headers[:-1]

        # 市況データを二次元リストに格納
        trade_data = []

        data_list = [0]
        for data in shikyo_data:
            class_name = data.get_attribute('class')
            if (class_name == 'st-td1 l') or (class_name == 'st-td2 l'):
                # 都市名を保持
                city_name = data.find_element_by_tag_name('span').text
            elif data.text == 'グラフ':
                trade_data.append(data_list)
                data_list = [0]
            else:
                if data_list[0] == 0:
                    data_list[0] = city_name
                data_list.append(data.text)

        # 市況データをデータフレームに格納し、必要な情報のみ残す
        df_trade_data = pd.DataFrame(trade_data, columns=trade_headers)
        df_trade_data.insert(0, '品目', item_name)
        df_trade_data.insert(0, '取引年月', trade_date[:6])
        df_trade_data.insert(0, '取引日', trade_date)
        df_trade_data.query("都市 == ['札幌市', '東京都', '大阪市', '福岡市']", inplace=True)
        dfs_trade_data.append(df_trade_data)

    return pd.concat(dfs_trade_data)


def send_df_to_slack(df):
    """取得したデータをSlackに送信する"""
    # データフレームから二次元リストに戻す
    trade_data = df.values.tolist()
    trade_headers = df.columns.tolist()

    # メッセージテキスト作成
    msg = f'{trade_data[0][0]}のキロ平均価格データ：<https://www.agrishikyo.jp/|netアグリ市況Webページ> ／ <https://docs.google.com/spreadsheets/d/1XnYcM8-dZVAgbSd-9yCCyhYYJ7Xg4-bHnPu4FJZKYyE|SHEET>\n\n'
    msg +=  '\t | \t'.join(trade_headers)
    msg += '\n'
    for row in trade_data:
        msg += '\t | \t'.join(row)
        msg += '\n'

    payload = {
        'text': msg,
        'icon_emoji': ':memo:',
        'username': '市場データ'
    }

    return requests.post(SLACK_WEBHOOK_URL, data=json.dumps(payload))


def lanch_browser():
    """ブラウザ立ち上げてログインする
    Return:
        selenium.WebBrowser"""
    # herokuのchromedriverのPATHを指定
    driver_path = '/app/.chromedriver/bin/chromedriver'
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    browser = webdriver.Chrome(options=options, executable_path=driver_path)
    # ログインページにアクセスしてログイン・閲覧コード入力
    browser.get(LOGIN_PAGE_URL)
    return browser


def login(browser):
    # ログインページ操作
    input_elms = browser.find_elements_by_tag_name('input')

    id_entry = input_elms[0]
    pw_entry = input_elms[1]
    login_btn = input_elms[2]

    id_entry.send_keys(USER_INFO_ID)
    pw_entry.send_keys(USER_INFO_PW)
    login_btn.click()

    # 閲覧コード入力ページ操作
    input_elms = browser.find_elements_by_tag_name('input')
    code_entry = input_elms[0]
    login_btn = input_elms[2]

    code_entry.send_keys(READ_CODE)
    login_btn.click()
    return None


def close_browser_with_logout(browser):
    logout_btn = browser.find_element_by_class_name('subnavi_logout')
    logout_btn.click()
    browser.quit()
    return None


def main_function():
    browser = lanch_browser()
    login(browser)
    time.sleep(3)

    # スクレイピングの実行: キロ単価
    df_unit_prices = scrape_unit_prices(browser, keywords_list2)
    time.sleep(3)
    send_df_to_slack(df_unit_prices)

    close_browser_with_logout(browser)

    return None


if __name__ == '__main__':
    main_function()
