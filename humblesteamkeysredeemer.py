import requests
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from fuzzywuzzy import fuzz
import steam.webauth as wa
import time
import pickle
from pwinput import pwinput
import os
import json
import sys
import webbrowser
import os
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
import atexit
import signal
from http.client import responses

#patch steam webauth for password feedback
wa.getpass = pwinput

if __name__ == "__main__":
    sys.stderr = open('error.log','a')

# Humble endpoints
HUMBLE_LOGIN_PAGE = "https://www.humblebundle.com/login"
HUMBLE_KEYS_PAGE = "https://www.humblebundle.com/home/library"
HUMBLE_SUB_PAGE = "https://www.humblebundle.com/subscription/"

HUMBLE_LOGIN_API = "https://www.humblebundle.com/processlogin"
HUMBLE_REDEEM_API = "https://www.humblebundle.com/humbler/redeemkey"
HUMBLE_ORDERS_API = "https://www.humblebundle.com/api/v1/user/order"
HUMBLE_ORDER_DETAILS_API = "https://www.humblebundle.com/api/v1/order/"
HUMBLE_SUB_API = "https://www.humblebundle.com/api/v1/subscriptions/humble_monthly/subscription_products_with_gamekeys/"

HUMBLE_PAY_EARLY = "https://www.humblebundle.com/subscription/payearly"
HUMBLE_CHOOSE_CONTENT = "https://www.humblebundle.com/humbler/choosecontent"

# Steam endpoints
STEAM_KEYS_PAGE = "https://store.steampowered.com/account/registerkey"
STEAM_USERDATA_API = "https://store.steampowered.com/dynamicstore/userdata/"
STEAM_REDEEM_API = "https://store.steampowered.com/account/ajaxregisterkey/"
STEAM_APP_LIST_API = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"

# May actually be able to do without these, but for now they're in.
headers = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def find_dict_keys(node, kv, parent=False):
    if isinstance(node, list):
        for i in node:
            for x in find_dict_keys(i, kv, parent):
               yield x
    elif isinstance(node, dict):
        if kv in node:
            if parent:
                yield node
            else:
                yield node[kv]
        for j in node.values():
            for x in find_dict_keys(j, kv, parent):
                yield x

getHumbleOrders = '''
var done = arguments[arguments.length - 1];
var list = '%optional%';
if (list){
    list = JSON.parse(list);
} else {
    list = [];
}
var getHumbleOrderDetails = async (list) => {
  const HUMBLE_ORDERS_API_URL = 'https://www.humblebundle.com/api/v1/user/order';
  const HUMBLE_ORDER_DETAILS_API = 'https://www.humblebundle.com/api/v1/order/';

  try {
    var orders = []
    if(list.length){
      orders = list.map(item => ({ gamekey: item }));
    } else {
      const response = await fetch(HUMBLE_ORDERS_API_URL);
      orders = await response.json();
    }
    const orderDetailsPromises = orders.map(async (order) => {
      const orderDetailsUrl = `${HUMBLE_ORDER_DETAILS_API}${order['gamekey']}?all_tpkds=true`;
      const orderDetailsResponse = await fetch(orderDetailsUrl);
      const orderDetails = await orderDetailsResponse.json();
      return orderDetails;
    });

    const orderDetailsArray = await Promise.all(orderDetailsPromises);
    return orderDetailsArray;
  } catch (error) {
    console.error('Error:', error);
    return [];
  }
};

getHumbleOrderDetails(list).then(r => {done(r)});
'''

fetch_cmd = '''
var done = arguments[arguments.length - 1];
var formData = new FormData();
const jsonData = JSON.parse(atob('{formData}'));

for (const key in jsonData) {{
    formData.append(key,jsonData[key])
}}

fetch("{url}", {{
  "headers": {{
    "csrf-prevention-token": "{csrf}"
    }},
  "body": formData,
  "method": "POST",
}}).then(r => {{ r.json().then( v=>{{done([r.status,v])}} ) }} );
'''

def perform_post(driver,url,payload):
    json_payload = b64encode(json.dumps(payload).encode('utf-8')).decode('ascii')
    csrf = driver.get_cookie('csrf_cookie')
    csrf = csrf['value'] if csrf is not None else ''
    if csrf is None:
        csrf = ''
    script = fetch_cmd.format(formData=json_payload,url=url,csrf=csrf)

    return driver.execute_async_script(fetch_cmd.format(formData=json_payload,url=url,csrf=csrf))

def process_quit(driver):
    def quit_on_exit(*args):
        driver.quit()

    atexit.register(quit_on_exit)
    signal.signal(signal.SIGTERM,quit_on_exit)
    signal.signal(signal.SIGINT,quit_on_exit)

def get_headless_driver():
    possibleDrivers = [(webdriver.Firefox,webdriver.FirefoxOptions),(webdriver.Chrome,webdriver.ChromeOptions)]
    driver = None

    exceptions = []
    for d,opt in possibleDrivers:
        try:
            options = opt()
            if d == webdriver.Chrome:
                options.add_argument("--headless=new")
            else:
                options.add_argument("-headless")
            driver = d(options=options)
            process_quit(driver) # make sure driver closes when we close
            return driver
        except WebDriverException as e:
            exceptions.append(('chrome:' if d == webdriver.Chrome else 'firefox:',e))
            continue
    cls()
    print("This script needs either Chrome or Firefox to be installed and the respective Web Driver for it to be configured (usually simplest is by placing it in the folder with the script)")
    print("")
    print("https://www.browserstack.com/guide/geckodriver-selenium-python")
    print("")
    print("Potential configuration hints:")
    for browser,exception in exceptions:
        print("")
        print(browser,exception.msg)

    time.sleep(30)
    sys.exit()

MODE_PROMPT = """Welcome to the Humble Exporter!
Which key export mode would you like to use?

[1] Auto-Redeem
[2] Export keys
[3] Humble Choice chooser
"""
def prompt_mode(order_details,humble_session):
    mode = None
    while mode not in ["1","2","3"]:
        print(MODE_PROMPT)
        mode = input("Choose 1, 2, or 3: ").strip()
        if mode in ["1","2","3"]:
            return mode
        print("Invalid mode")
    return mode


def valid_steam_key(key):
    # Steam keys are in the format of AAAAA-BBBBB-CCCCC
    if not isinstance(key, str):
        return False
    key_parts = key.split("-")
    return (
        len(key) == 17
        and len(key_parts) == 3
        and all(len(part) == 5 for part in key_parts)
    )


def try_recover_cookies(cookie_file, session):
    try:
        cookies = pickle.load(open(cookie_file,"rb"))
        if type(session) is requests.Session:
            # handle Steam session
            session.cookies.update(cookies)
        else:
            # handle WebDriver
            for cookie in cookies:
                session.add_cookie(cookie)
        return True
    except Exception as e:
        return False


def export_cookies(cookie_file, session):
    try:
        cookies = None
        if type(session) is requests.Session:
            # handle Steam session
            cookies = session.cookies
        else:
            # handle WebDriver
            cookies = session.get_cookies()
        pickle.dump(cookies, open(cookie_file,"wb"))
        return True
    except:
        return False

is_logged_in = '''
var done = arguments[arguments.length-1];

fetch("https://www.humblebundle.com/home/library").then(r => {done(!r.redirected)})
'''

def verify_logins_session(session):
    # Returns [humble_status, steam_status]
    if type(session) is requests.Session:
        loggedin = session.get(STEAM_KEYS_PAGE, allow_redirects=False).status_code not in (301,302)
        return [False,loggedin]
    else:
        return [session.execute_async_script(is_logged_in),False]

def do_login(driver,payload):
        auth,login_json = perform_post(driver,HUMBLE_LOGIN_API,payload)
        if auth not in (200,401):
            print(f"humblebundle.com has responded with an error (HTTP status code {auth}: {responses[auth]}).")
            time.sleep(30)
            sys.exit()
        return auth,login_json

def humble_login(driver):
    cls()
    driver.get(HUMBLE_LOGIN_PAGE)
    # Attempt to use saved session
    if try_recover_cookies(".humblecookies", driver) and verify_logins_session(driver)[0]:
        return True

    # Saved session didn't work
    authorized = False
    while not authorized:
        username = input("Humble Email: ")
        password = pwinput()


        payload = {
            "access_token": "",
            "access_token_provider_id": "",
            "goto": "/",
            "qs": "",
            "username": username,
            "password": password,
        }

        auth,login_json = do_login(driver,payload)

        if "errors" in login_json and "username" in login_json["errors"]:
            # Unknown email OR mismatched password
            print(login_json["errors"]["username"][0])
            continue

        while "humble_guard_required" in login_json or "two_factor_required" in login_json:
            # There may be differences for Humble's SMS 2FA, haven't tested.
            if "humble_guard_required" in login_json:
                humble_guard_code = input("Please enter the Humble security code: ")
                payload["guard"] = humble_guard_code.upper()
                # Humble security codes are case-sensitive via API, but luckily it's all uppercase!
                auth,login_json = do_login(driver,payload)

                if (
                    "user_terms_opt_in_data" in login_json
                    and login_json["user_terms_opt_in_data"]["needs_to_opt_in"]
                ):
                    # Nope, not messing with this.
                    print(
                        "There's been an update to the TOS, please sign in to Humble on your browser."
                    )
                    sys.exit()
            elif (
                "two_factor_required" in login_json and
                "errors" in login_json
                and "authy-input" in login_json["errors"]
            ):
                code = input("Please enter 2FA code: ")
                payload["code"] = code
                auth,login_json = do_login(driver,payload)
            elif "errors" in login_json:
                print("Unexpected login error detected.")
                print(login_json["errors"])
                raise Exception(login_json)
                sys.exit()
            
            if auth == 200:
                break

        export_cookies(".humblecookies", driver)
        return True


def steam_login():
    # Sign into Steam web

    # Attempt to use saved session
    r = requests.Session()
    if try_recover_cookies(".steamcookies", r) and verify_logins_session(r)[1]:
        return r

    # Saved state doesn't work, prompt user to sign in.
    s_username = input("Steam Username: ")
    user = wa.WebAuth(s_username)
    session = user.cli_login()
    export_cookies(".steamcookies", session)
    return session


def redeem_humble_key(sess, tpk):
    # Keys need to be 'redeemed' on Humble first before the Humble API gives the user a Steam key.
    # This triggers that for a given Humble key entry
    payload = {"keytype": tpk["machine_name"], "key": tpk["gamekey"], "keyindex": tpk["keyindex"]}
    status,respjson = perform_post(sess, HUMBLE_REDEEM_API, payload)
    
    if status != 200 or "error_msg" in respjson or not respjson["success"]:
        print("Error redeeming key on Humble for " + tpk["human_name"])
        if("error_msg" in respjson):
            print(respjson["error_msg"])
        return ""
    try:
        return respjson["key"]
    except:
        return respjson


def get_month_data(humble_session,month):
    # No real API for this, seems to just be served on the webpage.
    if type(humble_session) is not requests.Session:
        raise Exception("get_month_data needs a configured requests session")
    r = humble_session.get(HUMBLE_SUB_PAGE + month["product"]["choice_url"])

    data_indicator = f'<script id="webpack-monthly-product-data" type="application/json">'
    jsondata = r.text.split(data_indicator)[1].split("</script>")[0].strip()
    jsondata = json.loads(jsondata)
    return jsondata["contentChoiceOptions"]


def get_choices(humble_session,order_details):
    months = [
        month for month in order_details 
        if "choice_url" in month["product"] 
    ]

    # Oldest to Newest order
    months = sorted(months,key=lambda m: m["created"])
    request_session = requests.Session()
    for cookie in humble_session.get_cookies():
        # convert cookies to requests
        request_session.cookies.set(cookie['name'],cookie['value'],domain=cookie['domain'].replace('www.',''),path=cookie['path'])

    choices = []
    for month in months:
        if month["choices_remaining"] > 0 or month["product"].get("is_subs_v3_product",False): # subs v3 products don't advertise choices, need to get them exhaustively
            chosen_games = set(find_dict_keys(month["tpkd_dict"],"machine_name"))

            month["choice_data"] = get_month_data(request_session,month)
            if not month["choice_data"].get('canRedeemGames',True):
                month["available_choices"] = []
                continue

            v3 = not month["choice_data"].get("usesChoices",True)
            
            # Needed for choosing
            if v3:
                identifier = "initial"
                choice_options = month["choice_data"]["contentChoiceData"]["game_data"]
            else:
                identifier = "initial" if "initial" in month["choice_data"]["contentChoiceData"] else "initial-classic"
            
                if identifier not in month["choice_data"]["contentChoiceData"]:
                    for key in month["choice_data"]["contentChoiceData"].keys():
                        if "content_choices" in month["choice_data"]["contentChoiceData"][key]:
                            identifier = key

                choice_options = month["choice_data"]["contentChoiceData"][identifier]["content_choices"]

            # Exclude games that have already been chosen:
            month["available_choices"] = [
                    game[1]
                    for game in choice_options.items()
                    if set(find_dict_keys(game[1],"machine_name")).isdisjoint(chosen_games)
            ]
            
            month["parent_identifier"] = identifier
            if len(month["available_choices"]):
                yield month


def _redeem_steam(session, key, quiet=False):
    # Based on https://gist.github.com/snipplets/2156576c2754f8a4c9b43ccb674d5a5d
    if key == "":
        return 0
    session_id = session.cookies.get_dict()["sessionid"]
    r = session.post(
        STEAM_REDEEM_API,
        data={"product_key": key, "sessionid": session_id}
    )
    if r.status_code == 403:
        if not quiet:
            print(
                "Steam responded with 403 Forbidden while redeeming. "
                "This is likely session/cookie related. Please delete .steamcookies and try again; "
                "if it persists, wait an hour and retry."
            )
        return 53
    try:
        blob = r.json()
    except ValueError:
        # Steam occasionally returns HTML or empty responses; treat as transient failure
        body_preview = r.text[:200].replace("\n", " ")
        print(f"Error: Steam redemption response was not JSON (status {r.status_code}). Body preview: {body_preview}")
        return 53

    if blob["success"] == 1:
        for item in blob["purchase_receipt_info"]["line_items"]:
            print("Redeemed " + item["line_item_description"])
        return 0
    else:
        error_code = blob.get("purchase_result_details")
        if error_code == None:
            # Sometimes purchase_result_details isn't there for some reason, try alt method
            error_code = blob.get("purchase_receipt_info")
            if error_code != None:
                error_code = error_code.get("result_detail")
        error_code = error_code or 53

        if error_code == 14:
            error_message = (
                "The product code you've entered is not valid. Please double check to see if you've "
                "mistyped your key. I, L, and 1 can look alike, as can V and Y, and 0 and O. "
            )
        elif error_code == 15:
            error_message = (
                "The product code you've entered has already been activated by a different Steam account. "
                "This code cannot be used again. Please contact the retailer or online seller where the "
                "code was purchased for assistance. "
            )
        elif error_code == 53:
            error_message = (
                "There have been too many recent activation attempts from this account or Internet "
                "address. Please wait and try your product code again later. "
            )
        elif error_code == 13:
            error_message = (
                "Sorry, but this product is not available for purchase in this country. Your product key "
                "has not been redeemed. "
            )
        elif error_code == 9:
            error_message = (
                "This Steam account already owns the product(s) contained in this offer. To access them, "
                "visit your library in the Steam client. "
            )
        elif error_code == 24:
            error_message = (
                "The product code you've entered requires ownership of another product before "
                "activation.\n\nIf you are trying to activate an expansion pack or downloadable content, "
                "please first activate the original game, then activate this additional content. "
            )
        elif error_code == 36:
            error_message = (
                "The product code you have entered requires that you first play this game on the "
                "PlayStation®3 system before it can be registered.\n\nPlease:\n\n- Start this game on "
                "your PlayStation®3 system\n\n- Link your Steam account to your PlayStation®3 Network "
                "account\n\n- Connect to Steam while playing this game on the PlayStation®3 system\n\n- "
                "Register this product code through Steam. "
            )
        elif error_code == 50:
            error_message = (
                "The code you have entered is from a Steam Gift Card or Steam Wallet Code. Browse here: "
                "https://store.steampowered.com/account/redeemwalletcode to redeem it. "
            )
        else:
            error_message = (
                "An unexpected error has occurred.  Your product code has not been redeemed.  Please wait "
                "30 minutes and try redeeming the code again.  If the problem persists, please contact <a "
                'href="https://help.steampowered.com/en/wizard/HelpWithCDKey">Steam Support</a> for '
                "further assistance. "
            )
        if error_code != 53 or not quiet:
            print(error_message)
        return error_code


files = {}


def write_key(code, key):
    global files

    filename = "redeemed.csv"
    if code == 15 or code == 9:
        filename = "already_owned.csv"
    elif code != 0:
        filename = "errored.csv"

    if filename not in files:
        files[filename] = open(filename, "a", encoding="utf-8-sig")
    key["human_name"] = key["human_name"].replace(",", ".")
    gamekey = key.get('gamekey')
    human_name = key.get("human_name")
    redeemed_key_val = key.get("redeemed_key_val")
    output = f"{gamekey},{human_name},{redeemed_key_val}\n"
    files[filename].write(output)
    files[filename].flush()


def prompt_skipped(skipped_games):
    user_filtered = []
    with open("skipped.txt", "w", encoding="utf-8-sig") as file:
        for skipped_game in skipped_games.keys():
            file.write(skipped_game + "\n")

    print(
        f"Inside skipped.txt is a list of {len(skipped_games)} games that we think you already own, but aren't "
        f"completely sure "
    )
    try:
        input(
            "Feel free to REMOVE from that list any games that you would like to try anyways, and when done press "
            "Enter to confirm. "
        )
    except SyntaxError:
        pass
    if os.path.exists("skipped.txt"):
        with open("skipped.txt", "r", encoding="utf-8-sig") as file:
            user_filtered = [line.strip() for line in file]
        os.remove("skipped.txt")
    # Choose only the games that appear to be missing from user's skipped.txt file
    user_requested = [
        skip_game
        for skip_name, skip_game in skipped_games.items()
        if skip_name not in user_filtered
    ]
    return user_requested


def prompt_yes_no(question):
    ans = None
    answers = ["y","n"]
    while ans not in answers:
        prompt = f"{question} [{'/'.join(answers)}] "

        ans = input(prompt).strip().lower()
        if ans not in answers:
            print(f"{ans} is not a valid answer")
            continue
        else:
            return True if ans == "y" else False


def _load_steam_api_key(path="steam_api_key.txt"):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key
        except OSError:
            print(f"Warning: unable to read {path}; will prompt for Steam API key.")

    while True:
        key = input("Enter your Steam Web API key: ").strip()
        if key:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(key)
            except OSError:
                print(f"Warning: failed to save Steam API key to {path}; using it for this run only.")
            return key

        print("Steam API key cannot be empty. Please try again.")

def _fetch_all_apps(steam_session):
    # Steam limits app list responses; paginate until exhausted.
    api_key = _load_steam_api_key()
    url = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
    params = {
        "key": api_key,
        "max_results": 50000,
        "last_appid": 0,
        "include_dlc": True,
        "include_software": True,
        "include_hardware": True
    }

    print("Fetching partial Steam app list... (this may take a few moments)")

    apps = []
    while True:
        resp = steam_session.get(url, params=params)
        if resp.status_code == 403:
            print(
                "Steam responded with 403 Forbidden while fetching the app list. "
                "Please delete .steamcookies and try again. If the issue persists, wait an hour and retry."
            )
            sys.exit(1)

        body = resp.json().get("response", {})
        page = body.get("apps", [])
        apps.extend(page)

        if not body.get("have_more_results") or not page:
            break

        params["last_appid"] = body.get("last_appid", params.get("last_appid", 0))
    
    print(f"Fetched {len(apps)} total apps available on Steam Store.")

    return apps


def _fetch_missing_app_details(steam_session, app_ids):
    if not app_ids:
        return {}

    def fetch_app(appid):
        try:
            resp = steam_session.get(
                "https://store.steampowered.com/api/appdetails",
                params={"appids": appid},
            ).json()
            app_data = resp.get(str(appid), {})
            if app_data.get("success") and app_data.get("data"):
                name = app_data["data"].get("name")
                if name:
                    return appid, name
        except Exception:
            return None
        return None

    with ThreadPoolExecutor(max_workers=max(1, min(8, len(app_ids)))) as executor:
        results = list(executor.map(fetch_app, app_ids))

    resolved = dict(result for result in results if result is not None)
    unresolved = [appid for appid in app_ids if appid not in resolved]

    if unresolved:
        sample = ", ".join(str(appid) for appid in unresolved[:10])
        more = f" ... (+{len(unresolved) - 10} more)" if len(unresolved) > 10 else ""
        print(
            f"Warning: Unable to fetch details for {len(unresolved)} owned apps (examples: {sample}{more})"
        )
        try:
            with open("missing_app_ids.txt", "w", encoding="utf-8") as f:
                for appid in unresolved:
                    f.write(f"{appid}\n")
        except OSError:
            print("Warning: failed to write missing_app_ids.txt with unresolved app ids.")

    return resolved


def get_owned_apps(steam_session):
    resp = steam_session.get(STEAM_USERDATA_API)
    try:
        owned_content = resp.json()
    except ValueError:
        preview = resp.text[:200].replace("\n", " ")
        print(
            f"Error: Steam user data response was not JSON (status {resp.status_code}). "
            f"Body preview: {preview}"
        )
        return {}
    owned_app_ids = owned_content["rgOwnedPackages"] + owned_content["rgOwnedApps"]
    all_app_ids = _fetch_all_apps(steam_session)

    # Index known apps from the catalog
    app_index = {app["appid"]: app["name"] for app in all_app_ids}

    # Fallback: the new catalog endpoint omits store-disabled apps, so look them up directly.
    # Even with this, some apps may still be missing as Steam doesn't provide a full public catalog anymore and Humble may have ids for bundles/discontinued apps.
    unindexed_app_ids = [
        appid
        for appid in owned_content.get("rgOwnedApps", [])
        if appid not in app_index
    ]

    if unindexed_app_ids:
        app_index.update(_fetch_missing_app_details(steam_session, unindexed_app_ids))

    owned_app_details = {
        appid: app_index[appid]
        for appid in owned_content.get("rgOwnedApps", [])
        if appid in app_index
    }

    return owned_app_details

def match_ownership(owned_app_details, game, filter_live):
    threshold = 70
    best_match = (0, None)
    # Do a string search based on product names.
    matches = [
        (fuzz.token_set_ratio(appname, game["human_name"]), appid)
        for appid, appname in owned_app_details.items()
    ]
    refined_matches = [
        (fuzz.token_sort_ratio(owned_app_details[appid], game["human_name"]), appid)
        for score, appid in matches
        if score > threshold
    ]
    
    if filter_live and len(refined_matches) > 0:
        cls()
        best_match = max(refined_matches, key=lambda item: item[0])
        if best_match[0] == 100:
            return best_match
        print("steam games you own")
        for match in refined_matches:
            print(f"     {owned_app_details[match[1]]}: {match[0]}")
        if prompt_yes_no(f"Is \"{game['human_name']}\" in the above list?"):
            return refined_matches[0]
        else:
            return (0,None)
    else:
        if len(refined_matches) > 0:
            best_match = max(refined_matches, key=lambda item: item[0])
        elif len(refined_matches) == 1:
            best_match = refined_matches[0]
        if best_match[0] < 35:
            best_match = (0,None)
    return best_match

def prompt_filter_live():
    mode = None
    while mode not in ["y","n"]:
        mode = input("You can either see a list of games we think you already own later in a file, or filter them now. Would you like to see them now? [y/n] ").strip()
        if mode in ["y","n"]:
            return mode
        else:
            print("Enter y or n")
    return mode

def redeem_steam_keys(humble_session, humble_keys):
    session = steam_login()

    print("Successfully signed in on Steam.")
    print("Getting your owned content to avoid attempting to register keys already owned...")

    # Query owned App IDs according to Steam
    owned_app_details = get_owned_apps(session)

    noted_keys = [key for key in humble_keys if key["steam_app_id"] not in owned_app_details.keys()]
    skipped_games = {}
    unownedgames = []

    # Some Steam keys come back with no Steam AppID from Humble
    # So we do our best to look up from AppIDs (no packages, because can't find an API for it)

    filter_live = prompt_filter_live() == "y"

    for game in noted_keys:
        best_match = match_ownership(owned_app_details,game,filter_live)
        if best_match[1] is not None and best_match[1] in owned_app_details.keys():
            skipped_games[game["human_name"].strip()] = game
        else:
            unownedgames.append(game)

    print(
        "Filtered out game keys that you already own on Steam; {} keys unowned.".format(
            len(unownedgames)
        )
    )

    if len(skipped_games):
        # Skipped games uncertain to be owned by user. Let user choose
        unownedgames = unownedgames + prompt_skipped(skipped_games)
        print("{} keys will be attempted.".format(len(unownedgames)))
        # Preserve original order
        unownedgames = sorted(unownedgames,key=lambda g: humble_keys.index(g))
    
    redeemed = []

    for key in unownedgames:
        print(key["human_name"])

        if key["human_name"] in redeemed or (key["steam_app_id"] != None and key["steam_app_id"] in redeemed):
            # We've bumped into a repeat of the same game!
            write_key(9,key)
            continue
        else:
            if key["steam_app_id"] != None:
                redeemed.append(key["steam_app_id"])
            redeemed.append(key["human_name"])

        if "redeemed_key_val" not in key:
            # This key is unredeemed via Humble, trigger redemption process.
            redeemed_key = redeem_humble_key(humble_session, key)
            key["redeemed_key_val"] = redeemed_key
            # Worth noting this will only persist for this loop -- does not get saved to unownedgames' obj

        if not valid_steam_key(key["redeemed_key_val"]):
            # Most likely humble gift link
            write_key(1, key)
            continue

        code = _redeem_steam(session, key["redeemed_key_val"])
        animation = "|/-\\"
        seconds = 0
        while code == 53:
            """NOTE
            Steam seems to limit to about 50 keys/hr -- even if all 50 keys are legitimate *sigh*
            Even worse: 10 *failed* keys/hr
            Duplication counts towards Steam's _failure rate limit_,
            hence why we've worked so hard above to figure out what we already own
            """
            current_animation = animation[seconds % len(animation)]
            print(
                f"Waiting for rate limit to go away (takes an hour after first key insert) {current_animation}",
                end="\r",
            )
            time.sleep(1)
            seconds = seconds + 1
            if seconds % 60 == 0:
                # Try again every 60 seconds
                code = _redeem_steam(session, key["redeemed_key_val"], quiet=True)

        write_key(code, key)


def export_mode(humble_session,order_details):
    cls()

    export_key_headers = [
        'human_name',
        'redeemed_key_val',
        'is_gift',
        'key_type_human_name',
        'is_expired',
        'steam_ownership',
        'humble_steam_app_id',
        'humble_expired_at'
    ]

    steam_session = None
    reveal_unrevealed = False
    confirm_reveal = False

    owned_app_details = None

    keys = []
    
    print("Please configure your export:")
    export_steam_only = prompt_yes_no("Export only Steam keys?")
    export_revealed = prompt_yes_no("Export revealed keys?")
    export_unrevealed = prompt_yes_no("Export unrevealed keys?")
    if(not export_revealed and not export_unrevealed):
        print("That leaves 0 keys...")
        sys.exit()
    if(export_unrevealed):
        reveal_unrevealed = prompt_yes_no("Reveal all unrevealed keys? (This will remove your ability to claim gift links on these)")
        if(reveal_unrevealed):
            extra = "Steam " if export_steam_only else ""
            confirm_reveal = prompt_yes_no(f"Please CONFIRM that you would like ALL {extra}keys on Humble to be revealed, this can't be undone.")
    steam_config = prompt_yes_no("Would you like to sign into Steam to detect ownership on the export data?")
    
    if(steam_config):
        steam_session = steam_login()
        if(verify_logins_session(steam_session)[1]):
            owned_app_details = get_owned_apps(steam_session)
    
    desired_keys = "steam_app_id" if export_steam_only else "key_type_human_name"
    keylist = list(find_dict_keys(order_details,desired_keys,True))

    for idx,tpk in enumerate(keylist):
        revealed = "redeemed_key_val" in tpk
        export = (export_revealed and revealed) or (export_unrevealed and not revealed)

        if(export):
            if(export_unrevealed and confirm_reveal):
                # Redeem key if user requests all keys to be revealed
                tpk["redeemed_key_val"] = redeem_humble_key(humble_session,tpk)
            
            if(owned_app_details != None and "steam_app_id" in tpk):
                # User requested Steam Ownership info
                owned = tpk["steam_app_id"] in owned_app_details.keys()
                if(not owned):
                    # Do a search to see if user owns it
                    best_match = match_ownership(owned_app_details,tpk,False)
                    owned = best_match[1] is not None and best_match[1] in owned_app_details.keys()
                tpk["steam_ownership"] = owned

            # Surface IDs and expiry information for auditing mismatches
            tpk["humble_steam_app_id"] = tpk.get("steam_app_id")
            tpk["humble_expired_at"] = tpk.get("expiry_date")
            
            keys.append(tpk)
    
    ts = time.strftime("%Y%m%d-%H%M%S")
    filename = f"humble_export_{ts}.csv"
    with open(filename, 'w', encoding="utf-8-sig") as f:
        f.write(','.join(export_key_headers)+"\n")
        for key in keys:
            row = []
            for col in export_key_headers:
                if col in key:
                    row.append("\"" + str(key[col]) + "\"")
                else:
                    row.append("")
            f.write(','.join(row)+"\n")
    
    print(f"Exported to {filename}")


def choose_games(humble_session,choice_month_name,identifier,chosen):
    for choice in chosen:
        display_name = choice["display_item_machine_name"]
        if "tpkds" not in choice:
            webbrowser.open(f"{HUMBLE_SUB_PAGE}{choice_month_name}/{display_name}")
        else:
            payload = {
                "gamekey":choice["tpkds"][0]["gamekey"],
                "parent_identifier":identifier,
                "chosen_identifiers[]":display_name,
                "is_multikey_and_from_choice_modal":"false"
            }
            status,res = perform_post(driver,HUMBLE_CHOOSE_CONTENT,payload)
            if not ("success" in res or not res["success"]):
                print("Error choosing " + choice["title"])
                print(res)
            else:
                print("Chose game " + choice["title"])


def humble_chooser_mode(humble_session,order_details):
    try_redeem_keys = []
    months = get_choices(humble_session,order_details)
    count = 0
    first = True
    for month in months:
        redeem_all = None
        if(first):
            redeem_keys = prompt_yes_no("Would you like to auto-redeem these keys after? (Will require Steam login)")
            first = False
        
        ready = False
        while not ready:
            cls()
            if month["choice_data"]["usesChoices"]:
                remaining = month["choices_remaining"]
                print()
                print(month["product"]["human_name"])
                print(f"Choices remaining: {remaining}")
            else:
                remaining = len(month["available_choices"])
            print("Available Games:\n")
            choices = month["available_choices"]
            for idx,choice in enumerate(choices):
                title = choice["title"]
                rating_text = ""
                if("review_text" in choice["user_rating"] and "steam_percent|decimal" in choice["user_rating"]):
                    rating = choice["user_rating"]["review_text"].replace('_',' ')
                    percentage = str(int(choice["user_rating"]["steam_percent|decimal"]*100)) + "%"
                    rating_text = f" - {rating}({percentage})"
                exception = ""
                if "tpkds" not in choice:
                    # These are weird cases that should be handled by Humble.
                    exception = " (Must be redeemed through Humble directly)"
                print(f"{idx+1}. {title}{rating_text}{exception}")
            if(redeem_all == None and remaining == len(choices)):
                redeem_all = prompt_yes_no("Would you like to redeem all?")
            else:
                redeem_all = False
            
            if(redeem_all):
                user_input = [str(i+1) for i in range(0,len(choices))]
            else:
                if(redeem_keys):
                    auto_redeem_note = "(We'll auto-redeem any keys activated via the webpage if you continue after!)"
                else:
                    auto_redeem_note = ""
                print("\nOPTIONS:")
                print("To choose games, list the indexes separated by commas (e.g. '1' or '1,2,3')")
                print(f"Or type just 'link' to go to the webpage for this month {auto_redeem_note}")
                print("Or just press Enter to move on.")

                user_input = [uinput.strip() for uinput in input().split(',') if uinput.strip() != ""]

            if(len(user_input) == 0):
                ready = True
            elif(user_input[0].lower() == 'link'):
                webbrowser.open(HUMBLE_SUB_PAGE + month["product"]["choice_url"])
                if redeem_keys:
                    # May have redeemed keys on the webpage.
                    try_redeem_keys.append(month["gamekey"])
            else:
                invalid_option = lambda option: (
                    not option.isnumeric()
                    or option == "0" 
                    or int(option) > len(choices)
                )
                invalid = [option for option in user_input if invalid_option(option)]

                if(len(invalid) > 0):
                    print("Error interpreting options: " + ','.join(invalid))
                    time.sleep(2)
                else:
                    user_input = set(int(opt) for opt in user_input) # Uniques
                    chosen = [choice for idx,choice in enumerate(choices) if idx+1 in user_input]
                    # This weird enumeration is to keep it in original display order

                    if len(chosen) > remaining:
                        print(f"Too many games chosen, you have only {remaining} choices left")
                        time.sleep(2)
                    else:
                        print("\nGames selected:")
                        for choice in chosen:
                            print(choice["title"])
                        confirmed = prompt_yes_no("Please type 'y' to confirm your selection")
                        if confirmed:
                            choice_month_name = month["product"]["choice_url"]
                            identifier = month["parent_identifier"]
                            choose_games(humble_session,choice_month_name,identifier,chosen)
                            if redeem_keys:
                                try_redeem_keys.append(month["gamekey"])
                            ready = True
    if(first):
        print("No Humble Choices need choosing! Look at you all up-to-date!")
    else:
        print("No more unchosen Humble Choices")
        if(redeem_keys and len(try_redeem_keys) > 0):
            print("Redeeming keys now!")
            updated_monthlies = humble_session.execute_async_script(getHumbleOrders.replace('%optional%',json.dumps(try_redeem_keys)))
            chosen_keys = list(find_dict_keys(updated_monthlies,"steam_app_id",True))
            redeem_steam_keys(humble_session,chosen_keys)

def cls():
    os.system('cls' if os.name=='nt' else 'clear')
    print_main_header()

def print_main_header():
    print("-=FailSpy's Humble Bundle Helper!=-")
    print("--------------------------------------")
    
if __name__=="__main__":
    # Create a consistent session for Humble API use
    driver = get_headless_driver()
    humble_login(driver)
    print("Successfully signed in on Humble.")

    print(f"Getting order details, please wait")

    order_details = driver.execute_async_script(getHumbleOrders.replace('%optional%',''))

    desired_mode = prompt_mode(order_details,driver)
    if(desired_mode == "2"):
        export_mode(driver,order_details)
        sys.exit()
    if(desired_mode == "3"):
        humble_chooser_mode(driver,order_details)
        sys.exit()

    # Auto-Redeem mode
    cls()
    unrevealed_keys = []
    revealed_keys = []
    steam_keys = list(find_dict_keys(order_details,"steam_app_id",True))

    filters = ["errored.csv", "already_owned.csv", "redeemed.csv"]
    original_length = len(steam_keys)
    for filter_file in filters:
        try:
            with open(filter_file, "r") as f:
                keycols = f.read()
            filtered_keys = [keycol.strip() for keycol in keycols.replace("\n", ",").split(",")]
            steam_keys = [key for key in steam_keys if key.get("redeemed_key_val",False) not in filtered_keys]
        except FileNotFoundError:
            pass
    if len(steam_keys) != original_length:
        print("Filtered {} keys from previous runs".format(original_length - len(steam_keys)))

    for key in steam_keys:
        if "redeemed_key_val" in key:
            revealed_keys.append(key)
        else:
            # Has not been revealed via Humble yet
            unrevealed_keys.append(key)

    print(
        f"{len(steam_keys)} Steam keys total -- {len(revealed_keys)} revealed, {len(unrevealed_keys)} unrevealed"
    )

    will_reveal_keys = prompt_yes_no("Would you like to redeem on Humble as-yet un-revealed Steam keys?"
                                " (Revealing keys removes your ability to generate gift links for them)")
    if will_reveal_keys:
        try_already_revealed = prompt_yes_no("Would you like to attempt redeeming already-revealed keys as well?")
        # User has chosen to either redeem all keys or just the 'unrevealed' ones.
        redeem_steam_keys(driver, steam_keys if try_already_revealed else unrevealed_keys)
    else:
        # User has excluded unrevealed keys.
        redeem_steam_keys(driver, revealed_keys)

    # Cleanup
    for f in files:
        files[f].close()
