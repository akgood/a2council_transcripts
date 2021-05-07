import argparse
import collections
import datetime
from io import StringIO
import pprint
import re

import jellyfish
import webvtt

Block = collections.namedtuple(
    "Block", ["start", "end", "duration", "speaker", "speech"]
)

PLACEHOLDER_DATE = datetime.date(1970, 1, 1)
UNKNOWN_SPEAKER = "UNKNOWN"


def calc_duration(start_time, end_time):
    start_time = datetime.datetime.combine(
        PLACEHOLDER_DATE, datetime.time.fromisoformat(start_time)
    )
    end_time = datetime.datetime.combine(
        PLACEHOLDER_DATE, datetime.time.fromisoformat(end_time)
    )
    return (end_time - start_time).total_seconds()


def get_closest_match(query, knowns):
    """For a string 'query', find which string in the 'knowns' list has the lowest
    levenshtein edit distance."""
    (lowest_score, best_candidate) = min(
        (jellyfish.levenshtein_distance(query, candidate), candidate)
        for candidate in knowns
    )
    return best_candidate


def get_speech_blocks(captions, no_infer_speakers, known_speakers):
    # Implemented as a closure rather than a standalone function so we
    # can cache results in "speaker_map". We'll only run the
    # levenshtein distance checks when we encounter a typo we haven't
    # seen before!
    speaker_map = {s: s for s in known_speakers}
    blocks = []

    def infer_speaker(speaker):
        if no_infer_speakers:
            return speaker
        if speaker not in speaker_map:
            inferred_speaker = get_closest_match(speaker, known_speakers)
            speaker_map[speaker] = inferred_speaker
            return inferred_speaker
        else:
            return speaker_map[speaker]

    last_line = ""
    start_time = None
    end_time = None
    duration = 0
    current_speech = ""
    speaker = UNKNOWN_SPEAKER
    for idx, caption in enumerate(captions):
        # Apparently CTN's webvtt caption text are terminated in null bytes
        line = caption.text.strip("\r\n \u0000")

        # CTN also repeats captions, verbatim, quite frequently. You
        # can actually see this if you watch the video stream -
        # there's often two lines of captions overlayed on the video;
        # the top line is the previous text and the bottom line is the
        # newest (kindof like we're scrolling through a document on a
        # two-line screen).  The WebVTT file contains raw instructions
        # on what text to display when, so this means those lines
        # actually are duplicated in the file. We want to ignore any
        # lines' second occurrences, both to construct transcripts and
        # also to better-approximate speech durations.
        if line == last_line:
            continue
        last_line = line

        # CTN's convention appears to be that ">>" indicates a new
        # speaker. These are entered by hand, so be warned that
        # accuracy is not perfect.
        if line.startswith(">>"):
            # Record the previous speech "block" and start a new one
            if start_time is not None:
                blocks.append(
                    Block(start_time, end_time, duration, speaker, current_speech)
                )
            current_speech = line
            start_time = caption.start
            end_time = caption.end
            duration = 0

            # For the "regular cast" (councilmembers, mayor, attorney,
            # administrator), CTN will also insert the name of the
            # speaker after a ">>". For everybody else, they don't
            # make any attempt to identify who's talking.
            if ":" in line:
                # Typos are fairly common in speaker names, so we'll
                # try to correct them
                speaker = infer_speaker(line[2:].split(":")[0].strip().lower())
            else:
                speaker = UNKNOWN_SPEAKER
        else:
            # Append the line to the existing speech block, and extend
            # the end time to the end time of the latest caption
            current_speech += " " + line
            end_time = caption.end

        # We're calculating the "duration" of a speech block as the
        # total amount of time captions associated with a speaker
        # appear on the screen (except, excluding duplicates as noted
        # above). This is distinct from just doing "end time - start
        # time" on the assumption that maybe, if there's a long pause
        # in the middle of a speech, the captions will go away for a
        # while and we won't attribute silence as somebody's speaking
        # time. I don't know if this actually happens / makes any
        # difference in practice.
        duration += calc_duration(caption.start, caption.end)
    return blocks, speaker_map


def preprocess(webvtt_fp):
    """The "webvtt" module doesn't like something in the header content on CTN's
    VTT files, so here's a hack to just skip all the headers and return only the
    caption content itself, starting from the first timestamp'ed line."""

    timestamp_pattern = re.compile(r"^\d\d\:\d\d\:\d\d\.\d\d\d")

    # go line-by-line until we find a line starting with a timestamp
    file_pos = 0
    while True:
        line = webvtt_fp.readline()
        if not line:
            # End-of-file!
            raise Exception("No timestamp-like lines found!")
        if timestamp_pattern.match(line):
            break
        file_pos = webvtt_fp.tell()

    # go back to the beginning of that line
    webvtt_fp.seek(file_pos)

    # read the rest of the file, and prepend the magic "WEBVTT" header!
    return "WEBVTT\r\n" + webvtt_fp.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("captions_file")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--get-transcript",
        action="store_true",
        help="Output a reconstructed text transcript of all the captions",
    )
    group.add_argument(
        "--get-speaker-times",
        action="store_true",
        help="Calculate approximate total speaking times for each speaker",
    )
    group.add_argument(
        "--get-blocks",
        action="store_true",
        help=("Output raw information about all reconstructed speech blocks"),
    )
    parser.add_argument(
        "--no-infer-speakers",
        action="store_true",
        help=(
            "Don't attempt to correct typos by matching speaker names "
            "against a fixed set of known speakers."
        ),
    )
    parser.add_argument(
        "--speaker-list-file",
        help=(
            "Text file containing a list of known speaker names. Must be "
            'lowercase, one per line. (default: "known_speakers.txt")'
        ),
        default="known_speakers.txt",
    )
    args = parser.parse_args()

    with open(args.speaker_list_file, "r") as known_speakers_fp:
        known_speakers = [line.strip() for line in known_speakers_fp if line.strip()]
        # ensure this list also contains our unknown-speaker placeholder!
        known_speakers.append(UNKNOWN_SPEAKER)

    with open(args.captions_file, "r") as captions_fp:
        content = preprocess(captions_fp)

    captions = webvtt.read_buffer(StringIO(content))

    blocks, speaker_map = get_speech_blocks(
        captions, args.no_infer_speakers, known_speakers
    )

    if args.get_transcript:
        print("\n".join(b.speech for b in blocks))
    elif args.get_speaker_times:
        for k, v in speaker_map.items():
            if k != v:
                print("Inferred {} -> {}".format(k, v))
        print()

        speaker_times = {}
        for block in blocks:
            speaker_times[block.speaker] = (
                speaker_times.get(block.speaker, 0) + block.duration
            )
        pprint.pprint(speaker_times)
    elif args.get_blocks:
        for k, v in speaker_map.items():
            if k != v:
                print("Inferred {} -> {}".format(k, v))
        print()

        pprint.pprint(blocks)


if __name__ == "__main__":
    main()
