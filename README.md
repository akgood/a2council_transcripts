# Closed-Caption Data Parser for Ann Arbor City Council Meetings

Better docs coming soon ;)

## Where do I get the closed caption files?

It looks like CTN's closed captions files follow a predictable URL structure:

https://reflect-ctn.cablecast.tv/vod/[SHOWID]-CityCouncil[YYMMDD]-v1/captions.vtt

So, go to https://ctnvideo.a2gov.org/CablecastPublicSite/, find the meeting you're interested in, and figure out the show id by looking at the URL. For https://ctnvideo.a2gov.org/CablecastPublicSite/show/4896?channel=4, the show id is `4896`. Then contruct the date string (May 3, 2021 -> `210503`) for that meeting to get:

https://reflect-ctn.cablecast.tv/vod/4896-CityCouncil210503-v1/captions.vtt

If that fails, you can do what I did and use the chrome inspector to log all requests while playing the video (with captions on), and find the VTT file needle in that haystack...

## How do I use this?

Probably you'll want to do something like:

```
$ python3 -m venv ~/envs/a2council_transcripts
$ source ~/envs/a2council_transcripts/bin/activate
$ pip install -r requirements.txt
$ python3 parse_captions.py --get-transcript captions.vtt
$ python3 parse_captions.py --get-speaker-times captions.vtt
```
