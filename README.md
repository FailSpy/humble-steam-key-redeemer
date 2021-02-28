# humble-steam-key-redeemer
Python script to extract all Humble keys and redeem them on Steam automagically.

This is a script I hacked together to login to Humble and Steam, automating the redemption process. It's not perfect as I made this mostly for my own personal case and didn't test all possibilities: YMMV.

It will extract _all_ keys available for Steam from Humble, and check if any of the keys are already owned by the logged-in Steam user. Of those that aren't, attempt to redeem them on Steam.

This is dependent on [ValvePython/steam](https://github.com/ValvePython/steam) as well as [seatgeek/fuzzywuzzy](https://github.com/seatgeek/fuzzywuzzy)  
Install them with `pip install steam fuzzywuzzy`

Tested with Python 3.7.9
