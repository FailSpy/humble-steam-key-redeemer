import requests
from fuzzywuzzy import fuzz
import steam.webauth as wa
import time
import pickle

# Humble endpoints
humble_login_page = "https://www.humblebundle.com/login"
humble_keys_page = "https://www.humblebundle.com/home/library"

humble_login_api = "https://www.humblebundle.com/processlogin"
humble_redeem_api = "https://www.humblebundle.com/humbler/redeemkey"
humble_orders_api = "https://www.humblebundle.com/api/v1/user/order"
humble_order_details_api = "https://www.humblebundle.com/api/v1/order/"

# Steam endpoints
steam_keys_page = "https://store.steampowered.com/account/registerkey"
steam_userdata_api = "https://store.steampowered.com/dynamicstore/userdata/"
steam_redeem_api = "https://store.steampowered.com/account/ajaxregisterkey/"
steam_appslist_api = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"

# May actually be able to do without these, but for now they're in.
usefulheaders = {"Content-Type":"application/x-www-form-urlencoded", "Accept": "application/json, text/javascript, */*; q=0.01"}

def valid_steam_key(key):
    # Steam keys are in the format of AAAAA-BBBBB-CCCCC
    if not isinstance(key,str):
        return False
    validkeypart = lambda part: len(part) == 5
    keyparts = key.split('-')
    return len(key) == 17 and len(keyparts) == 3 and all([validkeypart(part) for part in keyparts])

def try_recover_cookies(cookiefile,session):
    try:
        with open(cookiefile,'rb') as f:
            session.cookies.update(pickle.load(f))
        return True
    except:
        return False
    
def export_cookies(cookiefile,session):
    try:
        with open(cookiefile,'wb') as f:
            pickle.dump(session.cookies,f)
        return True
    except:
        return False

def verify_logins_session(session):
    # Returns [humble_status, steam_status]
    loggedin = []
    for url in [humble_keys_page,steam_keys_page]:
        r = session.get(url,allow_redirects=False)
        loggedin.append(r.status_code != 301 and r.status_code != 302)
    return loggedin

def humble_login(session):
    # Attempt to use saved session
    if(try_recover_cookies('.humblecookies',session) and verify_logins_session(session)[0]):
        usefulheaders["CSRF-Prevention-Token"] = session.cookies['csrf_cookie']
        return True
    else:
        session.cookies.clear()
    
    # Saved session didn't work
    authorized = False
    while authorized == False:
        username = input("Humble bundle email:")
        password = input("Password:")
        csrfreq = session.get(humble_login_page)

        payload={"access_token":"","access_token_provider_id":"","goto":"/","qs":"","username":username,"password":password}
        usefulheaders["CSRF-Prevention-Token"] = csrfreq.cookies['csrf_cookie']

        r = session.post(humble_login_api,data=payload,headers=usefulheaders)
        loginjson = r.json()
        if("errors" in loginjson):
            print(loginjson['errors'])
            exit()
        else:
            twofactored = False
            while not twofactored:
                # There may be differences for Humble's SMS 2FA, haven't tested.
                if("humble_guard_required" in loginjson):
                    humble_guard_code = input("Please enter the Humble security code: ")
                    payload['guard'] = humble_guard_code.upper() # Humble security codes are case-sensitive via API, but luckily it's all uppercase!
                    auth = session.post(humble_login_api,data=payload,headers=usefulheaders)
                    authjson = auth.json()
                    
                    if('user_terms_opt_in_data' in authjson and authjson['user_terms_opt_in_data']['needs_to_opt_in']):
                        # Nope, not messing with this.
                        print("There's been an update to the TOS, please sign in to Humble on your browser.")
                        exit()
                    if(auth.status_code == 200):
                        twofactored = True
                elif(auth.status_code == 401):
                    print("Sorry, your two-factor isn't supported yet.")
                    exit()

            export_cookies('.humblecookies',session)
            return True

def steam_login():
    # Sign into Steam web
    
    # Attempt to use saved session
    r = requests.Session()
    if(try_recover_cookies('.steamcookies',r) and verify_logins_session(r)[1]):
        return r
    
    # Saved state doesn't work, prompt user to sign in.
    s_username = input("Steam Username:")
    user = wa.WebAuth(s_username)
    session = user.cli_login()
    export_cookies('.steamcookies',session)
    return session

def redeem_humble_key(sess,tpk):
    # Keys need to be 'redeemed' on Humble first before the Humble API gives the user a Steam key.
    # This triggers that for a given Humble key entry
    payload = {'keytype': tpk['machine_name'],'key':tpk['gamekey'],'keyindex':tpk['keyindex']}
    resp = sess.post(humble_redeem_api,data=payload,headers=usefulheaders)
    if(resp.status_code != 200 or not resp.json()['success']):
        print("Error redeeming key on Humble Bundle for " + tpk['human_name'])
        return ""
    return resp.json()['key']

def _redeem_steam(session,key,quiet=False):
    # Based on https://gist.github.com/snipplets/2156576c2754f8a4c9b43ccb674d5a5d
    if key == "":
        return 0
    sessionID = session.cookies.get_dict()["sessionid"]
    r = session.post(steam_redeem_api,data={'product_key':key,'sessionid':sessionID})
    blob = r.json()

    if blob["success"] == 1:
        for item in blob["purchase_receipt_info"]["line_items"]:
            print("Redeemed " + item["line_item_description"])
        return 0
    else:
        errorCode = blob["purchase_result_details"]
        sErrorMessage = ""
        if errorCode == 14:
            sErrorMessage = 'The product code you\'ve entered is not valid. Please double check to see if you\'ve mistyped your key. I, L, and 1 can look alike, as can V and Y, and 0 and O.'
        elif errorCode == 15:
            sErrorMessage = 'The product code you\'ve entered has already been activated by a different Steam account. This code cannot be used again. Please contact the retailer or online seller where the code was purchased for assistance.'
        elif errorCode == 53:
            sErrorMessage = 'There have been too many recent activation attempts from this account or Internet address. Please wait and try your product code again later.'
        elif errorCode == 13:
            sErrorMessage = 'Sorry, but this product is not available for purchase in this country. Your product key has not been redeemed.'
        elif errorCode == 9:
            sErrorMessage = 'This Steam account already owns the product(s) contained in this offer. To access them, visit your library in the Steam client.'
        elif errorCode == 24:
            sErrorMessage = 'The product code you\'ve entered requires ownership of another product before activation.\n\nIf you are trying to activate an expansion pack or downloadable content, please first activate the original game, then activate this additional content.'
        elif errorCode == 36:
            sErrorMessage = 'The product code you have entered requires that you first play this game on the PlayStation®3 system before it can be registered.\n\nPlease:\n\n- Start this game on your PlayStation®3 system\n\n- Link your Steam account to your PlayStation®3 Network account\n\n- Connect to Steam while playing this game on the PlayStation®3 system\n\n- Register this product code through Steam.'
        elif errorCode == 50: 
            sErrorMessage = 'The code you have entered is from a Steam Gift Card or Steam Wallet Code. Browse here: https://store.steampowered.com/account/redeemwalletcode to redeem it.'
        else:
            sErrorMessage = 'An unexpected error has occurred.  Your product code has not been redeemed.  Please wait 30 minutes and try redeeming the code again.  If the problem persists, please contact <a href="https://help.steampowered.com/en/wizard/HelpWithCDKey">Steam Support</a> for further assistance.'
        if(errorCode != 53 or not quiet):
            # 
            print(sErrorMessage)
        return errorCode

files = {}

def write_key(code,key):
    global files
    
    filename = "redeemed.csv"
    if code == 15 or code == 9:
        filename = "already_owned.csv"
    elif code != 0:
        filename = "errored.csv"
    
    if filename not in files:
        files[filename] = open(filename,'a')
    key['human_name'] = key['human_name'].replace(',','.')
    output = "{gamekey},{human_name},{redeemed_key_val}\n".format(**key)
    files[filename].write(output)
    files[filename].flush()

def prompt_skipped(skippedgames):
    user_filtered = []
    with open('skipped.txt','w') as f:
        for game in skippedgames.keys():
            f.write(game + "\n")

    print("Inside skipped.txt is a list of {skipped} games that we think you already own, but aren't completely sure".format(skipped=len(skippedgames)))
    try:
        input("Feel free to REMOVE from that list any games that you would like to try anyways, and when done press Enter to confirm.")
    except SyntaxError:
        pass

    with open('skipped.txt','r') as f:
        user_filtered = [line.strip() for line in f]
    
    # Choose only the games that appear to be missing from user's skipped.txt file
    user_requested = [skipgame for skipname,skipgame in skippedgames.items() if skipname not in user_filtered]
    return user_requested

def redeem_steam_keys(humble_session,humble_keys):
    session = steam_login()

    print("Successfully signed in on Steam.")
    print("Getting your owned content to avoid attempting to register keys already owned...")
    
    # Query owned App IDs according to Steam
    ownedcontent = session.get(steam_userdata_api).json()
    ownedappids = ownedcontent['rgOwnedPackages'] + ownedcontent['rgOwnedApps']
    ownedappdetails = {app['appid']:app['name'] for app in session.get(steam_appslist_api).json()['applist']['apps'] if app['appid'] in ownedappids}

    notedkeys = [key for key in humble_keys if key['steam_app_id'] not in ownedappids]
    skippedgames = {}
    unownedgames = []

    # Some Steam keys come back with no Steam AppID from Humble
    # So we do our best to look up from AppIDs (no packages, because can't find an API for it)
    threshold = 70
    for game in notedkeys:
        best_match = (None,None)
        # Do a string search based on product names.
        matches = [(fuzz.token_set_ratio(appname,game['human_name']),appid) for appid,appname in ownedappdetails.items()]
        if(len(matches) > 1):
            matches = [(fuzz.token_sort_ratio(ownedappdetails[appid],game['human_name']),appid) for score,appid in matches if score > threshold]
            if(len(matches) > 0):
                best_match = max(matches,key=lambda item:item[0])
        elif(len(matches) == 1):
            best_match = matches[0]
        if best_match[1] != None and best_match[1] in ownedappids:
            skippedgames[game['human_name'].strip()] = game
        else:
            unownedgames.append(game)

    print("Filtered out game keys that you already own on Steam; {} keys unowned.".format(len(unownedgames)))

    if len(skippedgames):
        # Skipped games uncertain to be owned by user. Let user choose
        unownedgames = unownedgames + prompt_skipped(skippedgames)
        print("{} keys will be attempted.".format(len(unownedgames)))

    for key in unownedgames:
        print(key['human_name'])

        if('redeemed_key_val' not in key):
            # This key is unredeemed via Humble, trigger redemption process.
            redeemed_key = redeem_humble_key(humble_session,key)
            key['redeemed_key_val'] = redeemed_key # Worth noting this will only persist for this loop -- does not get saved to unownedgames' obj
        
        if(not valid_steam_key(key['redeemed_key_val'])):
            # Most likely humble gift link
            write_key(1,key)
            continue

        code = _redeem_steam(session,key['redeemed_key_val'])
        animation = "|/-\\"
        seconds = 0
        while code == 53:
            ### NOTE
            # Steam seems to limit to about 50 keys/hr -- even if all 50 keys are legitimate *sigh*
            # Even worse: 10 *failed* keys/hr 
            # Duplication counts towards Steam's _failure rate limit_, hence why we've worked so hard above to figure out what we already own
            ###
            curanim = animation[seconds % len(animation)]
            print("Waiting for rate limit to go away (takes an hour after first key insert) " + curanim,end='\r')
            time.sleep(1)
            seconds = seconds + 1
            if(seconds % 60 == 0):
                # Try again every 60 seconds
                code = _redeem_steam(session,key['redeemed_key_val'],quiet=True)
        
        write_key(code,key)

# Create a consistent session for Humble API use
humble_session = requests.Session()
humble_login(humble_session)
print("Successfully signed in on Humble.")

orders = humble_session.get(humble_orders_api).json()
print("Getting {} order details, please wait".format(len(orders)))

# TODO: multithread this
order_details = [humble_session.get(f"{humble_order_details_api}{order['gamekey']}?all_tpkds=true").json() for order in orders]

unredeemed_keys = []
redeemed_keys = []
steam_keys = []
for game in order_details:
    if 'tpkd_dict' in game and 'all_tpks' in game['tpkd_dict']:
        steam_keys.extend([tpk for tpk in game['tpkd_dict']['all_tpks'] if tpk['key_type_human_name'] == 'Steam'])

filters = ['errored.csv','already_owned.csv','redeemed.csv']
original_length = len(steam_keys)
for filterfile in filters:
    try:
        with open(filterfile,'r') as f:
            keycols = f.read()
        filtered_keys = [keycol for keycol in keycols.replace('\n',',').split(',')]
        steam_keys = [key for key in steam_keys if key['gamekey'] not in filtered_keys]
    except:
        pass
if(len(steam_keys) != original_length):
    print('Filtered {} keys from previous runs'.format(original_length-len(steam_keys)))

for key in steam_keys:
    if 'redeemed_key_val' in key:
        redeemed_keys.append(key)
    else:
        # Has not been redeemed via Humble yet
        unredeemed_keys.append(key)

print("{keycnt} Steam keys -- {redeemedcnt} redeemed, {unredeemedcnt} unredeemed".format(keycnt=len(steam_keys),redeemedcnt=len(redeemed_keys),unredeemedcnt=len(unredeemed_keys)))


# TODO: Prompt the user for their preferences on redeeming on Steam all keys or subsets(redeemed, unredeemed, ambiguous, etc)

redeem_steam_keys(humble_session,steam_keys)

# Cleanup
for f in files:
    f.close()
