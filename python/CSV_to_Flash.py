#! env python3
# -*- coding: utf-8 -*-
import argparse
import io
import sys
import time
from math import ceil

import lib.cmdBinaryPacker as cbp
import lib.settingsBinaryPacker as sbp
import mido
import pandas as pd

MIDI_MANUF_ID = 0x7D

ERASE_FLASH = 52
WRITE_FLASH = 54
SYSEX_CMD_RESET = 60

# Flash pages are 1kByte
FLASH_PAGE_SIZE = 1024

# This needs to be in sync with flash_midi_settings.c where a number of flash
# pages to manage is hard-coded
ALLOWED_NUM_FLASH_PAGES = 3


def main(args: argparse.Namespace):
    # The mido module defines its symbols in a dynamic way that doesn't allow
    # type checking. So we have to ignore these lines from type checking.
    midi_inputs = [x for x in mido.get_input_names() if "STM" in x]  # type: ignore
    midi_outputs = [x for x in mido.get_output_names() if "STM" in x]  # type: ignore

    if len(midi_inputs) == 0:
        print("no input found")
        exit(1)

    if len(midi_outputs) == 0:
        print("no outputs found")
        exit(1)

    inputFile = args.csv_file

    with open(inputFile, "r") as f:
        raw_content = f.readlines()

    def remove_comments(content):
        # Discard all comment lines
        no_comments = []
        for l in raw_content:
            if "#" not in l:
                no_comments.append(l)
        return no_comments

    no_comments = remove_comments(raw_content)

    # Split into individual table sections
    title_lines = []
    for i, l in enumerate(no_comments):
        if "*" in l:
            title_lines.append((l.replace(",", " ").strip(" *"), i))

    df_dic = {}
    for i, tline in enumerate(title_lines):
        start_line = tline[1] + 1
        if i == len(title_lines) - 1:
            end_line = len(no_comments)
        else:
            end_line = title_lines[i + 1][1]
        frame_lines = no_comments[start_line:end_line]
        df = pd.read_csv(io.StringIO("\n".join(frame_lines)), delimiter=",").dropna(
            how="all"
        )
        df.drop(
            df.columns[df.columns.str.contains("unnamed", case=False)],
            axis=1,
            inplace=True,
        )
        df_dic[tline[0].strip()] = df

    # Setup the columns in the Button_Settings table
    df_dic["Button_Settings"].set_index(
        ["Bank_Number", "Button_Identifier"], inplace=True
    )
    df_dic["Global_Settings"].set_index(["Label"], inplace=True)
    df_dic["Bank_Naming"].set_index(["Bank_Number"], inplace=True)

    memory_bytes_list = []
    memory_bytes_list += sbp.pack_global_settings(df_dic["Global_Settings"])
    memory_bytes_list += sbp.pack_bank_strings(df_dic["Bank_Naming"])

    for index, row in df_dic["Button_Settings"].iterrows():
        memory_bytes_list += cbp.pack_row(row)

    flash_contents = bytes(memory_bytes_list)

    content_size = len(flash_contents)
    print(f"Flash content is {content_size} bytes = {content_size / 1024} kB")

    actual_num_flash_pages = ceil(content_size / FLASH_PAGE_SIZE)
    if actual_num_flash_pages > ALLOWED_NUM_FLASH_PAGES:
        print(
            f"WARNING: Your configuration requires {actual_num_flash_pages} "
            f"flash pages which is more than the {ALLOWED_NUM_FLASH_PAGES} pages "
            "allowed"
        )

    ans = input("Continue? (y/N) ").lower().strip()

    if ans != "y":
        sys.exit(1)

    # File is now converted to a byte array, this will be loaded to the flash.

    inport = mido.open_input(midi_inputs[0])  # type: ignore
    outport = mido.open_output(midi_outputs[0])  # type: ignore

    # Erase Flash settings pages
    print("Erasing Flash Settings")
    outmsg = mido.Message("sysex", data=[MIDI_MANUF_ID, ERASE_FLASH, 0x42, 0x24])
    outport.send(outmsg)

    # Wait for response
    time.sleep(0.05)
    inmsg = inport.receive()
    print("Erase Complete")

    no_chunks = int(len(flash_contents) / 16)
    for x in range(0, no_chunks):
        print("Writing Flash Chunk: ", x + 1, "/", no_chunks)

        flash_chunk_low_byte = x & 0x7F
        flash_chunk_high_byte = (x >> 7) & 0x7F

        data = [
            MIDI_MANUF_ID,
            WRITE_FLASH,
            flash_chunk_high_byte,
            flash_chunk_low_byte,
        ]

        for i in range(0, 16):
            data += [flash_contents[x * 16 + i] >> 4]
            data += [flash_contents[x * 16 + i] & 0xF]

        outmsg = mido.Message("sysex", data=data)

        outport.send(outmsg)
        inmsg = inport.receive()
        time.sleep(0.01)

    print("Finshed, reseting device...")
    outmsg = mido.Message("sysex", data=[MIDI_MANUF_ID, SYSEX_CMD_RESET])
    outport.send(outmsg)

    inport.close()
    outport.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="This is a tool to load a CSV configuration to the Midi Commander device. "
        "First, plug the Midi Commander to the USB port and turn it on. Then, run this tool "
        "by giving it as input the CSV file downloaded from the Google Spreadsheet configuration.",
    )
    p.add_argument(
        "csv_file",
        help="Path to a CSV file downloaded from the Google Spreadsheet configuration",
    )
    args = p.parse_args()
    main(args)
