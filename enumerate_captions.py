import datetime
import logging
import json
from pathlib import Path
import urllib.request

from parse_captions import parse


def get_date_from_show(show):
    # XXX fromisoformat does not like the full date-time here, so
    # we'll just grab the date portion and cut off the time.
    try:
        # field #6 seems to be "Original Event Date"
        (date_field,) = [x for x in show["customFields"] if x["showField"] == 6]
        return datetime.datetime.fromisoformat(date_field["value"].split("T")[0])
    except Exception as e:
        logging.warning("Original date for show {} not found: {}".format(show["id"], e))
        try:
            # try to parse the date that's usually part of the show title
            return datetime.datetime.strptime(show["title"][-6:], "%y%m%d")
        except Exception as e:
            # eventDate exists always, but is sometimes inaccurate
            return datetime.datetime.fromisoformat(show["eventDate"].split("T")[0])


def retrieve_captions_for_vod(vod, workdir="raw_captions"):
    show_info_url = "https://reflect-ctn.cablecast.tv/cablecastapi/v1/shows/{}".format(
        vod["show"]
    )
    logging.info("fetching show info: {}".format(show_info_url))
    with urllib.request.urlopen(show_info_url) as r:
        body = json.loads(r.read())
    show = body["show"]


    title = show["title"]
    show_id = show["id"]
    event_date = get_date_from_show(show)

    # the VOD URLs all end in "vod.mp4"; there is also a "vod.m3u8"
    # which sometimes references a "captions.m3u8" which points to a
    # "captions.vtt" file. This appears to be consistent for all
    # recordings so far, so we'll just skip a few steps and attempt to
    # download "captions.vtt" directly. (This could change in the
    # future, in which case we may be better off fetching the m3u8
    # files and parsing them).
    vod_url = vod["url"]
    caption_url = "{}/captions.vtt".format(vod_url.rsplit("/", maxsplit=1)[0])
    logging.info("Attempting to download captions: {}".format(caption_url))

    try:
        p = Path(
            workdir,
            "{}-{}-{}.vtt".format(event_date.strftime("%Y-%m-%d"), title, show_id),
        )
        filename, headers = urllib.request.urlretrieve(caption_url, filename=str(p))
        p = Path(filename)
        if p.stat().st_size < 100:
            logging.info("Captions for {} were empty; deleting".format(title))
            p.unlink()

    except Exception as e:
        logging.info("Could not download captions for {}: {}".format(show["title"], e))


def fetch_new_raw_captions(known_vods):
    known_vods = set(known_vods)

    # XXX We could store the last page number visited and start from
    # there on subsequent script runs; however, because VOD IDs do not
    # appear in order, there appears to be no firm guarantee that new
    # ones would appear "at the end". So, for now we'll fetch the
    # entire set, every time
    page = 0
    page_size = 100

    while True:
        vod_list_url = "https://reflect-ctn.cablecast.tv/cablecastapi/v1/vods?page_size={}&offset={}".format(
            page_size, page
        )
        logging.info("Fetching list of VODs: {}".format(vod_list_url))
        with urllib.request.urlopen(vod_list_url) as r:
            body = json.loads(r.read())

        for v in body["vods"]:
            if v["id"] in known_vods:
                logging.debug("Skipping previously-seen vod {}".format(v["id"]))
                continue
            retrieve_captions_for_vod(v)
            known_vods.add(v["id"])

        if ((page + 1) * page_size) > body["meta"]["count"]:
            break
        page += 1

    return known_vods


def parse_new_captions(srcdir="raw_captions", dstdir="transcripts"):
    for src_filepath in Path(srcdir).iterdir():
        src_filename = src_filepath.name
        if not src_filename.endswith(".vtt"):
            continue

        dest_filename = src_filename[:-4] + ".txt"
        dest_filepath = Path(dstdir, dest_filename)

        if dest_filepath.exists():
            continue

        logging.info("Parsing {}".format(src_filename))
        with open(src_filepath, "r") as fp:
            try:
                captions = parse(fp, no_infer_speakers=True)
            except Exception as e:
                logging.warning("Error parsing {}: {}".format(src_filepath, e))
                continue

        with open(dest_filepath, "w") as fp:
            fp.write(captions.get_transcript())


def main():
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s", level=logging.DEBUG
    )

    # We'll maintain a set of all VOD (Video On Demand,
    # i.e. recordings from CTN) ids we've previously seen, so we don't
    # re-download them each time this script runs. We need to do it
    # this way because the API, for some reason, does not return them
    # in increasing order
    known_vods = set()

    try:
        with open("state.json", "r") as fp:
            state = json.load(fp)
    except FileNotFoundError:
        state = {"known_vods": []}

    known_vods = fetch_new_raw_captions(state["known_vods"])
    parse_new_captions()

    with open("state.json", "w") as fp:
        state = {"known_vods": sorted(known_vods)}
        json.dump(state, fp)


if __name__ == "__main__":
    main()
