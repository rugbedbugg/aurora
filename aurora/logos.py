"""ASCII logos of common distributions. A {1} or {2} in a line switches to that tone.

The art comes from fastfetch (https://github.com/fastfetch-cli/fastfetch). Its licence follows.

MIT License

Copyright (c) 2021-2023 Linus Dierheimer
Copyright (c) 2022-2026 Carter Li

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

LOGOS = {
    "nixos": [
        "{1}          ▗▄▄▄       {2}▗▄▄▄▄    ▄▄▄▖",
        "          {1}▜███▙       {2}▜███▙  ▟███▛",
        "           {1}▜███▙       {2}▜███▙▟███▛",
        "            {1}▜███▙       {2}▜██████▛",
        "     {1}▟█████████████████▙ {2}▜████▛     {1}▟▙",
        "    {1}▟███████████████████▙ {2}▜███▙    {1}▟██▙",
        "           {2}▄▄▄▄▖           ▜███▙  {1}▟███▛",
        "          {2}▟███▛             ▜██▛ {1}▟███▛",
        "         {2}▟███▛               ▜▛ {1}▟███▛",
        "{2}▟███████████▛                  {1}▟██████████▙",
        "{2}▜██████████▛                  {1}▟███████████▛",
        "      {2}▟███▛ {1}▟▙               ▟███▛",
        "     {2}▟███▛ {1}▟██▙             ▟███▛",
        "    {2}▟███▛  {1}▜███▙           ▝▀▀▀▀",
        "    {2}▜██▛    {1}▜███▙ {2}▜██████████████████▛",
        "     {2}▜▛     {1}▟████▙ {2}▜████████████████▛",
        "           {1}▟██████▙         {2}▜███▙",
        "          {1}▟███▛▜███▙         {2}▜███▙",
        "         {1}▟███▛  ▜███▙         {2}▜███▙",
        "         {1}▝▀▀▀    ▀▀▀▀▘         {2}▀▀▀▘",
    ],
    "arch": [
        "{1}                  -`",
        "                 .o+`",
        "                `ooo/",
        "               `+oooo:",
        "              `+oooooo:",
        "              -+oooooo+:",
        "            `/:-:++oooo+:",
        "           `/++++/+++++++:",
        "          `/++++++++++++++:",
        "         `/+++o{2}oooooooo{1}oooo/`",
        "        ./{2}ooosssso++osssssso{1}+`",
        "{2}       .oossssso-````/ossssss+`",
        "      -osssssso.      :ssssssso.",
        "     :osssssss/        osssso+++.",
        "    /ossssssss/        +ssssooo/-",
        "  `/ossssso+/:-        -:/+osssso+-",
        " `+sso+:-`                 `.-/+oso:",
        "`++:.                           `-/+/",
        ".`                                 `/",
    ],
    "debian": [
        "{1}        {2}_,met$$$$$gg.",
        "     ,g$$$$$$$$$$$$$$$P.",
        '   ,g$$P""       """Y$$.".',
        "  ,$$P'              `$$$.",
        "',$$P       ,ggs.     `$$b:",
        "`d$$'     ,$P\"'   {1}.{2}    $$$",
        " $$P      d$'     {1},{2}    $$P",
        " $$:      $$.   {1}-{2}    ,d$$'",
        " $$;      Y$b._   _,d$P'",
        ' Y$$.    {1}`.{2}`"Y$$$$P"\'',
        ' `$$b      {1}"-.__',
        "  {2}`Y$$b",
        "   `Y$$.",
        "     `$$b.",
        "       `Y$$b.",
        '         `"Y$b._',
        '             `""""',
    ],
    "ubuntu": [
        "{1}                             ....",
        "              {2}.',:clooo:  {1}.:looooo:.",
        "           {2}.;looooooooc  {1}.oooooooooo'",
        "        {2}.;looooool:,''.  {1}:ooooooooooc",
        "       {2};looool;.         {1}'oooooooooo,",
        "      {2};clool'             {1}.cooooooc.  {2},,",
        "         {2}...                {1}......  {2}.:oo,",
        "  {1}.;clol:,.                        {2}.loooo'",
        " {1}:ooooooooo,                        {2}'ooool",
        "{1}'ooooooooooo.                        {2}loooo.",
        "{1}'ooooooooool                         {2}coooo.",
        " {1},loooooooc.                        {2}.loooo.",
        "   {1}.,;;;'.                          {2};ooooc",
        "       {2}...                         ,ooool.",
        "    {2}.cooooc.              {1}..',,'.  {2}.cooo.",
        "      {2};ooooo:.           {1};oooooooc.  {2}:l.",
        "       {2}.coooooc,..      {1}coooooooooo.",
        "         {2}.:ooooooolc:. {1}.ooooooooooo'",
        "           {2}.':loooooo;  {1},oooooooooc",
        "               {2}..';::c'  {1}.;loooo:'",
    ],
    "fedora": [
        "{1}             .',;::::;,'.",
        "         .';:cccccccccccc:;,.",
        "      .;cccccccccccccccccccccc;.",
        "    .:cccccccccccccccccccccccccc:.",
        "  .;ccccccccccccc;{2}.:dddl:.{1};ccccccc;.",
        " .:ccccccccccccc;{2}OWMKOOXMWd{1};ccccccc:.",
        ".:ccccccccccccc;{2}KMMc{1};cc;{2}xMMc{1};ccccccc:.",
        ",cccccccccccccc;{2}MMM.{1};cc;{2};WW:{1};cccccccc,",
        ":cccccccccccccc;{2}MMM.{1};cccccccccccccccc:",
        ":ccccccc;{2}oxOOOo{1};{2}MMM000k.{1};cccccccccccc:",
        "cccccc;{2}0MMKxdd:{1};{2}MMMkddc.{1};cccccccccccc;",
        "ccccc;{2}XMO'{1};cccc;{2}MMM.{1};cccccccccccccccc'",
        "ccccc;{2}MMo{1};ccccc;{2}MMW.{1};ccccccccccccccc;",
        "ccccc;{2}0MNc.{1}ccc{2}.xMMd{1};ccccccccccccccc;",
        "cccccc;{2}dNMWXXXWM0:{1};cccccccccccccc:,",
        "cccccccc;{2}.:odl:.{1};cccccccccccccc:,.",
        "ccccccccccccccccccccccccccccc:'.",
        ":ccccccccccccccccccccccc:;,..",
        " ':cccccccccccccccc::;,.",
    ],
    "linux": [
        "{1}        {2}#####",
        "       {2}#######",
        "       {2}##{1}O{2}#{1}O{2}##",
        "       {2}#######",
        "     {2}##{1}#######{2}##",
        "    {2}#{1}##########{2}##",
        "   {2}#{1}############{2}##",
        "   {2}#{1}############{2}###",
        "  ##{2}#{1}###########{2}###",
        "######{2}#{1}#######{2}#######",
        "#######{2}#{1}#####{2}########",
        "  #####{2}############",
    ],
}
SMALL = {
    "nixos": [
        "{1}  \\\\  {2}\\\\ //",
        "{1} ==\\\\__{2}\\\\/ {1}//",
        "{2}   //   \\\\{1}//",
        "{2}==//     {1}//==",
        "{2} //{1}\\\\{2}___{1}//",
        "{2}// {1}/\\\\  {2}\\\\==",
        "  {1}// \\\\  {2}\\\\",
    ],
    "arch": [
        "{1}      /\\",
        "     /  \\",
        "    /    \\",
        "   /      \\",
        "{2}  /   ,,   \\",
        " /   |  |   \\",
        "/_-''    ''-_\\",
    ],
    "debian": [
        "{1}  _____",
        " /  __ \\",
        "|  /    |",
        "|  \\___-",
        "-_",
        "  --_",
    ],
    "ubuntu": [
        "{1}       {2}..;,; {1}.,;,.",
        "    {2}.,lool: {1}.ooooo,",
        "   {2};oo;:    {1}.coool.",
        " {1}....         ''' {2},l;",
        "{1}:oooo,            {2}'oo.",
        "{1}looooc            {2}:oo'",
        " {1}'::'             {2},oo:",
        "   {2},.,       {1}.... {2}co,",
        "    {2}lo:;.   {1}:oooo; {2}.",
        "     {2}':ooo; {1}cooooc",
        "        {2}'''  {1}''''",
    ],
    "fedora": [
        "{1}        ,'''''.",
        "       |   ,.  |",
        "       |  |  '_'",
        "  ,....|  |..",
        ".'  ,_;|   ..'",
        "|  |   |  |",
        "|  ',_,'  |",
        " '.     ,'",
        "   '''''",
    ],
    "linux": [
        "{1}    ___",
        "   ({2}.. {1}\\",
        "   (<> {1}|",
        "  /{2}/  \\ {1}\\",
        " ( {2}|  | {1}/|",
        "_{1}/\\ {2}__){1}/_)",
        "\\/{1}-____\\/",
    ],
}
FAMILY = {"arch": "arch", "debian": "debian", "ubuntu": "ubuntu", "fedora": "fedora", "nixos": "nixos"}


def os_release(path="/etc/os-release"):
    """Return the KEY=VALUE pairs of the os-release file. Return an empty dict when it cannot be read."""
    pairs = {}
    try:
        with open(path) as f:
            for line in f:
                key, sep, value = line.strip().partition("=")
                if sep:
                    pairs[key] = value.strip("\"'")
    except OSError:
        pass
    return pairs


def detect(path="/etc/os-release"):
    """Return the logo key and the display name of this OS."""
    info = os_release(path)
    for ident in [info.get("ID", ""), *info.get("ID_LIKE", "").split()]:
        if ident in FAMILY:
            return FAMILY[ident], info.get("NAME", ident)
    return "linux", info.get("NAME", "Linux")


def tones(lines):
    """Split logo lines into rows of (tone, text) segments. Tone 1 is the default."""
    rows = []
    for line in lines:
        row, tone, buf, i = [], 1, "", 0
        while i < len(line):
            if line[i] == "{" and line[i + 1 : i + 3] in ("1}", "2}"):
                if buf:
                    row.append((tone, buf))
                tone, buf, i = int(line[i + 1]), "", i + 3
            else:
                buf += line[i]
                i += 1
        if buf:
            row.append((tone, buf))
        rows.append(row)
    return rows


def size(lines):
    """Return the height and width of a logo."""
    return len(lines), max(sum(len(text) for _, text in row) for row in tones(lines))


def pick(key, room, unicode=True):
    """Return the largest logo of a distribution that fits room rows. Return None when none fits.

    Without unicode only the logos made of ASCII characters count.
    """
    for lines in (LOGOS[key], SMALL[key]):
        if size(lines)[0] <= room and (unicode or all(ord(c) < 128 for line in lines for c in line)):
            return lines
    return None
