# humble-steam-key-redeemer

Python script to extract all Humble keys and redeem them on Steam automagically.

This is primarily designed to be a set-it-and-forget-it tool that maximizes successful entry of keys into Steam, assuring that no Steam game goes unredeemed.

This script will login to both Humble and Steam, automating the whole process. It's not perfect as I made this mostly for my own personal case and couldn't test all possibilities so YMMV. Feel free to send submit an issue if you do bump into issues.

It will extract _all_ keys available for Steam from Humble, and check if any of the keys are already owned by the logged-in Steam user. Of those that aren't, attempt to redeem them on Steam. This is done because Steam has some pretty harsh rate limiting on key redemption -- 50 keys/hr, or 10 failed keys/hr, whichever comes first.

## Getting started

### Doing it yourself

First install python 3.6 and run `run_redeemer.bat` (on windows). Make sure to install the [gecko driver as well](https://www.browserstack.com/guide/geckodriver-selenium-python).

### Using Nix

For OSX/Linux/WSL, if you install `nix` (more information [here](https://nixos.org/download.html)), you can then use `nix develop` in the terminal, which will download python & set up selenium for you.

### Notes

To remove an already added account, delete the associated `.(humble|steam)cookies` file.

Other janitorial files:
`cookies.txt` - An unpicked source of your .humblecookies
`.browser_options` - A pickle of the browser options you pick initially (tor etc)

### Dependencies

Requires Python version 3.6 or above

- `steam`: [ValvePython/steam](https://github.com/ValvePython/steam)
- `fuzzywuzzy`: [seatgeek/fuzzywuzzy](https://github.com/seatgeek/fuzzywuzzy)
- `requests`: [requests](https://requests.readthedocs.io/en/master/)
- `requests-futures`: [ross/requests-futures](https://github.com/ross/requests-futures)
- `cloudscraper`: [VeNoMouS/cloudscraper](https://github.com/VeNoMouS/cloudscraper)
- `selenium`: [selenium](https://pypi.org/project/selenium/)
- `python-Levenshtein`: [ztane/python-Levenshtein](https://github.com/ztane/python-Levenshtein) **OPTIONAL**

Install the required dependencies with

```
pip install -r requirements.txt
```

If you want to install `python-Levenshtein`:

```
pip install python-Levenshtein
```
