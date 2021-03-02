import requests
from fuzzywuzzy import fuzz
import steam.webauth as wa
import time
import pickle
import getpass

# Humble endpoints
HUMBLE_LOGIN_PAGE = "https://www.humblebundle.com/login"
HUMBLE_KEYS_PAGE = "https://www.humblebundle.com/home/library"

HUMBLE_LOGIN_API = "https://www.humblebundle.com/processlogin"
HUMBLE_REDEEM_API = "https://www.humblebundle.com/humbler/redeemkey"
HUMBLE_ORDERS_API = "https://www.humblebundle.com/api/v1/user/order"
HUMBLE_ORDER_DETAILS_API = "https://www.humblebundle.com/api/v1/order/"

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

MODE_PROMPT = """Welcome to the Humble Exporter!
Which key export mode would you like to use?

[1] Auto-Redeem
[2] Export keys
"""
def prompt_mode(order_details,humble_session):
    mode = None
    while mode not in ["1","2"]:
        print(MODE_PROMPT)
        mode = input("Choose 1 or 2: ").strip()
        if mode in ["1","2"]:
            return mode
        else:
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
        and all([len(part) == 5])
    )


def try_recover_cookies(cookie_file, session):
    try:
        with open(cookie_file, "rb") as file:
            session.cookies.update(pickle.load(file))
        return True
    except:
        return False


def export_cookies(cookie_file, session):
    try:
        with open(cookie_file, "wb") as file:
            pickle.dump(session.cookies, file)
        return True
    except:
        return False


def verify_logins_session(session):
    # Returns [humble_status, steam_status]
    loggedin = []
    for url in [HUMBLE_KEYS_PAGE, STEAM_KEYS_PAGE]:
        r = session.get(url, allow_redirects=False)
        loggedin.append(r.status_code != 301 and r.status_code != 302)
    return loggedin


def humble_login(session):
    # Attempt to use saved session
    if try_recover_cookies(".humblecookies", session) and verify_logins_session(session)[0]:
        headers["CSRF-Prevention-Token"] = session.cookies["csrf_cookie"]
        return True
    else:
        session.cookies.clear()

    # Saved session didn't work
    authorized = False
    while not authorized:
        username = input("Humble Email: ")
        password = getpass.getpass("Password: ")
        csrf_req = session.get(HUMBLE_LOGIN_PAGE)

        payload = {
            "access_token": "",
            "access_token_provider_id": "",
            "goto": "/",
            "qs": "",
            "username": username,
            "password": password,
        }
        headers["CSRF-Prevention-Token"] = session.cookies["csrf_cookie"]

        r = session.post(HUMBLE_LOGIN_API, data=payload, headers=headers)
        login_json = r.json()

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
                auth = session.post(HUMBLE_LOGIN_API, data=payload, headers=headers)
                login_json = auth.json()

                if (
                    "user_terms_opt_in_data" in login_json
                    and login_json["user_terms_opt_in_data"]["needs_to_opt_in"]
                ):
                    # Nope, not messing with this.
                    print(
                        "There's been an update to the TOS, please sign in to Humble on your browser."
                    )
                    exit()
            elif (
                "two_factor_required" in login_json and 
                "errors" in login_json 
                and "authy-input" in login_json["errors"]
            ):
                code = input("Please enter 2FA code: ")
                payload["code"] = code
                auth = session.post(HUMBLE_LOGIN_API, data=payload, headers=headers)
                login_json = r.json()
            elif "errors" in login_json:
                print("Unexpected login error detected.")
                print(login_json["errors"])
                exit()
            
            if auth != None and auth.status_code == 200:
                break

        export_cookies(".humblecookies", session)
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
    resp = sess.post(HUMBLE_REDEEM_API, data=payload, headers=headers)
    if resp.status_code != 200 or not resp.json()["success"]:
        print("Error redeeming key on Humble for " + tpk["human_name"])
        return ""
    return resp.json()["key"]


def _redeem_steam(session, key, quiet=False):
    # Based on https://gist.github.com/snipplets/2156576c2754f8a4c9b43ccb674d5a5d
    if key == "":
        return 0
    session_id = session.cookies.get_dict()["sessionid"]
    r = session.post(STEAM_REDEEM_API, data={"product_key": key, "sessionid": session_id})
    blob = r.json()

    if blob["success"] == 1:
        for item in blob["purchase_receipt_info"]["line_items"]:
            print("Redeemed " + item["line_item_description"])
        return 0
    else:
        error_code = blob["purchase_result_details"]
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
        files[filename] = open(filename, "a")
    key["human_name"] = key["human_name"].replace(",", ".")
    output = "{gamekey},{human_name},{redeemed_key_val}\n".format(**key)
    files[filename].write(output)
    files[filename].flush()


def prompt_skipped(skipped_games):
    user_filtered = []
    with open("skipped.txt", "w") as file:
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

    with open("skipped.txt", "r") as file:
        user_filtered = [line.strip() for line in file]

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

def get_owned_apps(steam_session):
    owned_content = steam_session.get(STEAM_USERDATA_API).json()
    owned_app_ids = owned_content["rgOwnedPackages"] + owned_content["rgOwnedApps"]
    owned_app_details = {
        app["appid"]: app["name"]
        for app in steam_session.get(STEAM_APP_LIST_API).json()["applist"]["apps"]
        if app["appid"] in owned_app_ids
    }
    return owned_app_details

def match_ownership(owned_app_details, game):
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
    if len(refined_matches) > 0:
        best_match = max(refined_matches, key=lambda item: item[0])
    elif len(refined_matches) == 1:
        best_match = refined_matches[0]
    return best_match


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

    for game in noted_keys:
        best_match = match_ownership(owned_app_details,game)
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

    for key in unownedgames:
        print(key["human_name"])

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
    export_key_headers = ['human_name','redeemed_key_val','is_gift','key_type_human_name','is_expired','steam_ownership']

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
        exit()
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
    
    for game in order_details:
        if "tpkd_dict" in game and "all_tpks" in game["tpkd_dict"]:
            for idx,tpk in enumerate(game["tpkd_dict"]["all_tpks"]):
                revealed = "redeemed_key_val" in tpk
                steam_key = tpk["key_type_human_name"] == "Steam"
                valid_key_type = not export_steam_only or steam_key
                export = (
                    valid_key_type and 
                    (
                        (export_revealed and revealed) or 
                        (export_unrevealed and not revealed)
                    )
                )

                if(export):
                    if(export_unrevealed and confirm_reveal):
                        # Redeem key if user requests all keys to be revealed
                        tpk = redeem_humble_key(humble_session,key)
                    if(owned_app_details and steam_key):
                        # User requested Steam Ownership info
                        owned = tpk["steam_app_id"] in owned_app_details.keys()
                        if(not owned):
                            # Do a search to see if user owns it
                            best_match = match_ownership(owned_app_details,tpk)
                            owned = best_match[1] is not None and best_match[1] in owned_app_details.keys()
                        tpk["steam_ownership"] = owned
                    keys.append(tpk)
    
    ts = time.strftime("%Y%m%d-%H%M%S")
    filename = f"humble_export_{ts}.csv"
    with open(filename,'w') as f:
        f.write(','.join(export_key_headers)+"\n")
        for key in keys:
            row = []
            for col in export_key_headers:
                if col in key:
                    row.append(str(key[col]))
                else:
                    row.append("")
            f.write(','.join(row)+"\n")
    
    print(f"Exported to {filename}")

    
# Create a consistent session for Humble API use
humble_session = requests.Session()
humble_login(humble_session)
print("Successfully signed in on Humble.")

orders = humble_session.get(HUMBLE_ORDERS_API).json()
print(f"Getting {len(orders)} order details, please wait")

# TODO: multithread this
order_details = [
    humble_session.get(f"{HUMBLE_ORDER_DETAILS_API}{order['gamekey']}?all_tpkds=true").json()
    for order in orders
]

desired_mode = prompt_mode(order_details,humble_session)
print(desired_mode)
if(desired_mode == "2"):
    export_mode(humble_session,order_details)
    exit()

# Auto-Redeem
unrevealed_keys = []
revealed_keys = []
steam_keys = []
for game in order_details:
    if "tpkd_dict" in game and "all_tpks" in game["tpkd_dict"]:
        steam_keys.extend(
            [tpk for tpk in game["tpkd_dict"]["all_tpks"] if tpk["key_type_human_name"] == "Steam"]
        )

filters = ["errored.csv", "already_owned.csv", "redeemed.csv"]
original_length = len(steam_keys)
for filter_file in filters:
    try:
        with open(filter_file, "r") as f:
            keycols = f.read()
        filtered_keys = [keycol for keycol in keycols.replace("\n", ",").split(",")]
        steam_keys = [key for key in steam_keys if key["gamekey"] not in filtered_keys]
    except:
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
    redeem_steam_keys(humble_session, steam_keys if try_already_revealed else unrevealed_keys)
else:
    # User has excluded unrevealed keys.
    redeem_steam_keys(humble_session, revealed_keys)

# Cleanup
for f in files:
    f.close()
