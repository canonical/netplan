// Copyright (C) 2026 Canonical, Ltd.
// SPDX-License-Identifier: GPL-3.0-only
//
// This program is free software; you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation; version 3.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <http://www.gnu.org/licenses/>.

//! The subset of python3-rich (13.x) that `netplan status` relies on:
//! `Console(highlighter=NetplanHighlighter(), theme=..., width=None,
//! emoji=False).print(markup)`.
//!
//! Reproduced: terminal/colour detection (`FORCE_COLOR`, `NO_COLOR`, `TERM`,
//! `COLORTERM`, isatty), the console width (`COLUMNS`/`LINES`, terminal
//! size, default 80), console markup (tags, escapes, `MarkupError`),
//! stripping of control codes, the regex highlighter, word wrapping and
//! folding (`Text.wrap`, `divide_line`, cell widths) and the SGR escape
//! sequences of styled segments.

use anyhow::Result;

use crate::py::Exception;

#[derive(Clone, Copy, PartialEq)]
enum ColorSystem {
    Standard,
    EightBit,
    TrueColor,
}

#[derive(Clone, Copy, PartialEq, Default)]
struct Style {
    bold: bool,
    color: Option<&'static str>,
}

impl Style {
    const NULL: Style = Style {
        bold: false,
        color: None,
    };

    fn bold(color: &'static str) -> Style {
        Style {
            bold: true,
            color: Some(color),
        }
    }

    fn color(color: &'static str) -> Style {
        Style {
            bold: false,
            color: Some(color),
        }
    }

    /// `Style.combine`: later styles win for colours, attributes add up.
    fn add(self, other: Style) -> Style {
        Style {
            bold: self.bold || other.bold,
            color: other.color.or(self.color),
        }
    }
}

const COLOR_NAMES: &[&str] = &[
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "white",
    "bright_black",
    "bright_red",
    "bright_green",
    "bright_yellow",
    "bright_blue",
    "bright_magenta",
    "bright_cyan",
    "bright_white",
];

/// `Color.downgrade(system).get_ansi_codes()`
fn color_codes(color: &str, system: ColorSystem) -> String {
    if color == "grey62" {
        return match system {
            ColorSystem::Standard => "37".into(),
            _ => "38;5;247".into(),
        };
    }
    match COLOR_NAMES.iter().position(|c| *c == color) {
        Some(n) if n < 8 => format!("{}", 30 + n),
        Some(n) => format!("{}", 90 + n - 8),
        None => String::new(),
    }
}

/// `Style.parse()` for the few style definitions that can show up
/// (unknown ones render as the null style, like rich's `get_style` default).
fn parse_style(name: &str) -> Style {
    let mut style = Style::NULL;
    for word in name.split_whitespace() {
        match word {
            "bold" | "b" => style.bold = true,
            "grey62" => style.color = Some("grey62"),
            w => match COLOR_NAMES.iter().find(|c| **c == w) {
                Some(c) => style.color = Some(c),
                None => return Style::NULL,
            },
        }
    }
    style
}

/// The NetplanHighlighter/theme setup of `NetplanStatus._create_pretty_print`.
pub struct Console {
    diff: bool,
    color_system: Option<ColorSystem>,
    no_color: bool,
    width: usize,
}

fn env(name: &str) -> Option<String> {
    std::env::var_os(name).map(|v| v.to_string_lossy().into_owned())
}

fn isdigit(s: &str) -> bool {
    !s.is_empty() && s.chars().all(|c| c.is_ascii_digit())
}

fn terminal_width() -> Option<usize> {
    for fd in 0..3 {
        let mut ws: nix::libc::winsize = nix::libc::winsize {
            ws_row: 0,
            ws_col: 0,
            ws_xpixel: 0,
            ws_ypixel: 0,
        };
        // SAFETY: TIOCGWINSZ writes a `winsize` struct to the pointer we pass,
        // which points to a valid, initialised local.
        if unsafe { nix::libc::ioctl(fd, nix::libc::TIOCGWINSZ, &mut ws) } == 0 {
            return Some(ws.ws_col as usize);
        }
    }
    None
}

impl Console {
    pub fn new(diff: bool) -> Console {
        // Console.is_terminal: FORCE_COLOR (any value) or sys.stdout.isatty()
        let is_terminal =
            env("FORCE_COLOR").is_some() || nix::unistd::isatty(std::io::stdout()).unwrap_or(false);
        let term = env("TERM").unwrap_or_default();
        let is_dumb = is_terminal && matches!(term.to_lowercase().as_str(), "dumb" | "unknown");
        let color_system = if !is_terminal || is_dumb {
            None
        } else {
            let colorterm = env("COLORTERM").unwrap_or_default().trim().to_lowercase();
            if colorterm == "truecolor" || colorterm == "24bit" {
                Some(ColorSystem::TrueColor)
            } else {
                let term = term.trim().to_lowercase();
                let colors = term.rsplit('-').next().unwrap_or("");
                Some(match colors {
                    "kitty" | "256color" => ColorSystem::EightBit,
                    _ => ColorSystem::Standard,
                })
            }
        };
        let columns = env("COLUMNS").filter(|c| isdigit(c));
        let lines = env("LINES").filter(|c| isdigit(c));
        let fixed_width: Option<usize> = columns.as_ref().and_then(|c| c.parse().ok());
        let width = if fixed_width.is_some() && lines.is_some() {
            fixed_width.unwrap_or(80)
        } else if is_dumb {
            80
        } else {
            let mut w = terminal_width().unwrap_or(0);
            if let Some(c) = fixed_width {
                w = c;
            }
            if w == 0 {
                w = 80;
            }
            fixed_width.unwrap_or(w)
        };
        Console {
            diff,
            color_system,
            no_color: env("NO_COLOR").is_some(),
            width,
        }
    }

    fn get_style(&self, name: &str) -> Style {
        match name {
            "netplan.int" if self.diff => Style::color("grey62"),
            "netplan.str" if self.diff => Style::color("grey62"),
            "netplan.int" => Style::bold("cyan"),
            "netplan.str" => Style::color("yellow"),
            "muted" => Style::color("grey62"),
            "online" => Style::bold("green"),
            "offline" => Style::bold("red"),
            "unknown" => Style::bold("yellow"),
            "highlight" => Style {
                bold: true,
                color: None,
            },
            _ => parse_style(name),
        }
    }

    /// `console.print()`
    pub fn print_empty(&self) {
        crate::py::write_stdout("\n");
        crate::py::flush_stdout();
    }

    /// `console.print(markup)`
    pub fn print(&self, markup: &str) -> Result<()> {
        let (mut plain, mut spans) = render_markup(markup)?;
        highlight(&plain, &mut spans);
        let mut out = String::new();
        // Text.wrap(): each "\n"-separated line is wrapped on its own.
        let mut lines: Vec<(Vec<char>, Vec<Span>)> = vec![];
        let mut start = 0;
        let mut ranges = vec![];
        for (i, c) in plain.iter().enumerate() {
            if *c == '\n' {
                ranges.push((start, i));
                start = i + 1;
            }
        }
        ranges.push((start, plain.len()));
        for (ls, le) in ranges {
            let mut text: Vec<char> = plain[ls..le].to_vec();
            let mut line_spans = clip_spans(&spans, ls, le);
            if text.contains(&'\t') {
                (text, line_spans) = expand_tabs(&text, &line_spans);
            }
            let s: String = text.iter().collect();
            let offsets = divide_line(&s, self.width);
            let mut bounds = vec![0];
            bounds.extend(offsets);
            bounds.push(text.len());
            for w in bounds.windows(2) {
                let (a, mut b) = (w[0], w[1]);
                // rstrip_end(width)
                let len = b - a;
                if len > self.width {
                    let excess = len - self.width;
                    let ws = text[a..b]
                        .iter()
                        .rev()
                        .take_while(|c| py_isspace(**c))
                        .count();
                    b -= ws.min(excess);
                }
                // truncate(width, overflow="fold")
                let mut sub: Vec<char> = text[a..b].to_vec();
                if cell_len(&sub) > self.width {
                    sub = set_cell_size(&sub, self.width);
                }
                let sub_spans = clip_spans(&line_spans, a, a + sub.len().min(b - a));
                lines.push((sub, sub_spans));
            }
        }
        plain.clear();
        spans.clear();
        for (i, (text, sub_spans)) in lines.into_iter().enumerate() {
            if i > 0 {
                plain.push('\n');
            }
            let offset = plain.len();
            spans.extend(sub_spans.into_iter().map(|s| Span {
                start: s.start + offset,
                end: s.end + offset,
                ..s
            }));
            plain.extend(text);
        }
        self.render(&plain, &spans, &mut out);
        out.push('\n');
        crate::py::write_stdout(&out);
        crate::py::flush_stdout();
        Ok(())
    }

    /// `Text.render()` + `Console._render_buffer()`
    fn render(&self, plain: &[char], spans: &[Span], out: &mut String) {
        let Some(system) = self.color_system else {
            out.extend(plain.iter());
            return;
        };
        let mut bounds: Vec<usize> = vec![0, plain.len()];
        for s in spans {
            bounds.push(s.start);
            bounds.push(s.end);
        }
        bounds.sort_unstable();
        bounds.dedup();
        for w in bounds.windows(2) {
            let (a, b) = (w[0], w[1]);
            if b <= a {
                continue;
            }
            let mut active: Vec<&Span> =
                spans.iter().filter(|s| s.start <= a && s.end > a).collect();
            active.sort_by_key(|s| s.index);
            let mut style = active
                .iter()
                .fold(Style::NULL, |acc, s| acc.add(self.get_style(&s.style)));
            if self.no_color {
                style.color = None;
            }
            let text: String = plain[a..b].iter().collect();
            if style == Style::NULL {
                out.push_str(&text);
                continue;
            }
            let mut codes = vec![];
            if style.bold {
                codes.push("1".to_string());
            }
            if let Some(c) = style.color {
                let c = color_codes(c, system);
                if !c.is_empty() {
                    codes.push(c);
                }
            }
            if codes.is_empty() {
                out.push_str(&text);
            } else {
                out.push_str(&format!("\x1b[{}m{}\x1b[0m", codes.join(";"), text));
            }
        }
    }
}

#[derive(Clone)]
struct Span {
    start: usize,
    end: usize,
    style: String,
    /// position in the Text's span list (combination order)
    index: usize,
}

fn clip_spans(spans: &[Span], a: usize, b: usize) -> Vec<Span> {
    spans
        .iter()
        .filter(|s| s.start < b && s.end > a)
        .map(|s| Span {
            start: s.start.max(a) - a,
            end: s.end.min(b) - a,
            style: s.style.clone(),
            index: s.index,
        })
        .filter(|s| s.end > s.start)
        .collect()
}

/// `str.isspace()` / `\s`
pub fn py_isspace(c: char) -> bool {
    c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)
}

/// rich.control.strip_control_codes
fn strip_control_codes(s: &str) -> String {
    s.chars()
        .filter(|c| !matches!(*c as u32, 7 | 8 | 11 | 12 | 13))
        .collect()
}

/// `rich.markup.render(markup, emoji=False)`: the plain text and the spans
/// in the order rich keeps them (`sorted(spans[::-1], key=start)`).
fn render_markup(markup: &str) -> Result<(Vec<char>, Vec<Span>)> {
    if !markup.contains('[') {
        return Ok((strip_control_codes(markup).chars().collect(), vec![]));
    }
    let m: Vec<char> = markup.chars().collect();
    let mut text: Vec<char> = vec![];
    let mut stack: Vec<(usize, String)> = vec![];
    let mut spans: Vec<(usize, usize, String)> = vec![];
    let append = |text: &mut Vec<char>, s: &[char]| {
        let s: String = s.iter().collect();
        let s = s.replace("\\[", "[");
        text.extend(strip_control_codes(&s).chars());
    };
    let mut position = 0;
    let mut i = 0;
    // RE_TAGS = r"((\\*)\[([a-z#/@][^[]*?)])", searched left to right
    while i < m.len() {
        // a match starts at i: backslashes, then "[", tag start char,
        // lazily up to the first "]" with no "[" in between
        let mut j = i;
        while j < m.len() && m[j] == '\\' {
            j += 1;
        }
        let tag_ok = j + 1 < m.len()
            && m[j] == '['
            && (m[j + 1].is_ascii_lowercase() || matches!(m[j + 1], '#' | '/' | '@'));
        let close = if tag_ok {
            (j + 1..m.len())
                .take_while(|&k| m[k] != '[')
                .find(|&k| m[k] == ']')
        } else {
            None
        };
        let Some(close) = close else {
            i += 1;
            continue;
        };
        let (start, end) = (i, close + 1);
        let escapes = j - i;
        let tag_text: String = m[j + 1..close].iter().collect();
        if start > position {
            append(&mut text, &m[position..start]);
        }
        let mut tag_start = start;
        if escapes > 0 {
            let (backslashes, escaped) = (escapes / 2, escapes % 2);
            if backslashes > 0 {
                text.extend(std::iter::repeat_n('\\', backslashes));
                tag_start += backslashes * 2;
            }
            if escaped == 1 {
                append(&mut text, &m[j..end]);
                position = end;
                i = end;
                continue;
            }
        }
        let name = tag_text
            .split_once('=')
            .map_or(tag_text.as_str(), |(n, _)| n);
        let params = tag_text.split_once('=').map(|(_, p)| p.to_string());
        if let Some(closing) = name.strip_prefix('/') {
            let style_name = closing.trim();
            let open = if !style_name.is_empty() {
                let style_name = style_name.to_lowercase();
                match stack.iter().rposition(|(_, n)| *n == style_name) {
                    Some(k) => stack.remove(k),
                    None => {
                        return Err(Exception::err(
                            "rich.errors.MarkupError",
                            format!(
                                "closing tag '[{tag_text}]' at position {tag_start} doesn't match any open tag"
                            ),
                        ))
                    }
                }
            } else {
                match stack.pop() {
                    Some(o) => o,
                    None => {
                        return Err(Exception::err(
                            "rich.errors.MarkupError",
                            format!(
                                "closing tag '[/]' at position {tag_start} has nothing to close"
                            ),
                        ))
                    }
                }
            };
            spans.push((open.0, text.len(), open.1));
        } else {
            let normalized = name.trim().to_lowercase();
            let full = match params {
                Some(p) => format!("{normalized} {p}"),
                None => normalized,
            };
            stack.push((text.len(), full));
        }
        position = end;
        i = end;
    }
    if position < m.len() {
        append(&mut text, &m[position..]);
    }
    let len = text.len();
    while let Some((start, name)) = stack.pop() {
        if !name.is_empty() {
            spans.push((start, len, name));
        }
    }
    spans.reverse();
    spans.sort_by_key(|s| s.0);
    let spans = spans
        .into_iter()
        .enumerate()
        .map(|(i, (start, end, style))| Span {
            start,
            end,
            style,
            index: i + 1,
        })
        .collect();
    Ok((text, spans))
}

/// NetplanHighlighter: `(^|[\s\/])(?P<int>\d+)([\s:]?\s|$)` and
/// `(?P<str>(\"|\').+(\"|\'))`, applied with `Text.highlight_regex`; the
/// spans are put in front of the markup spans in `spans`.
fn highlight(t: &[char], spans: &mut Vec<Span>) {
    let n = t.len();
    let ws = |i: usize| i < n && py_isspace(t[i]);
    let dollar = |i: usize| i == n || (i + 1 == n && t[i] == '\n');
    let mut found = vec![];
    let mut i = 0;
    while i < n {
        let mut matched = None;
        let prefixes: Vec<usize> = [
            (i == 0).then_some(i),
            (ws(i) || t[i] == '/').then_some(i + 1),
        ]
        .into_iter()
        .flatten()
        .collect();
        for j in prefixes {
            let mut k = j;
            while k < n && t[k].is_ascii_digit() {
                k += 1;
            }
            if k == j {
                continue;
            }
            // backtracking over shorter digit runs can never succeed: the
            // next character would be a digit
            let end = if k < n && (ws(k) || t[k] == ':') && ws(k + 1) {
                Some(k + 2)
            } else if ws(k) {
                Some(k + 1)
            } else if dollar(k) {
                Some(k)
            } else {
                None
            };
            if let Some(end) = end {
                matched = Some((j, k, end));
                break;
            }
        }
        match matched {
            Some((j, k, end)) => {
                found.push((j, k, "netplan.int"));
                i = end;
            }
            None => i += 1,
        }
    }
    let quote = |c: char| c == '"' || c == '\'';
    let mut i = 0;
    while i < n {
        if quote(t[i]) {
            let line_end = (i + 1..n).find(|&k| t[k] == '\n').unwrap_or(n);
            if let Some(q) = (i + 2..line_end).rev().find(|&k| quote(t[k])) {
                found.push((i, q + 1, "netplan.str"));
                i = q + 1;
                continue;
            }
        }
        i += 1;
    }
    // Console.render_str() highlights the plain text and then copies the
    // markup spans over: the highlighter's spans come first.
    let count = found.len();
    for s in spans.iter_mut() {
        s.index += count;
    }
    let hl = found
        .into_iter()
        .enumerate()
        .map(|(k, (start, end, style))| Span {
            start,
            end,
            style: style.to_string(),
            index: k + 1,
        });
    spans.splice(0..0, hl);
}

/// `Text.expand_tabs(8)` for a single line
fn expand_tabs(text: &[char], spans: &[Span]) -> (Vec<char>, Vec<Span>) {
    let mut out = vec![];
    let mut map = vec![];
    let mut cell = 0;
    for &c in text {
        map.push(out.len());
        if c == '\t' {
            out.push(' ');
            cell += 1;
            let rem = cell % 8;
            if rem != 0 {
                out.extend(std::iter::repeat_n(' ', 8 - rem));
                cell += 8 - rem;
            }
        } else {
            out.push(c);
            cell += char_width(c);
        }
    }
    map.push(out.len());
    // The line is split after each tab and joined again: spans are cut at
    // those points; a span reaching the end of a part covers its padding.
    let mut cuts: Vec<usize> = vec![0];
    cuts.extend(
        text.iter()
            .enumerate()
            .filter(|(_, c)| **c == '\t')
            .map(|(i, _)| i + 1),
    );
    if *cuts.last().unwrap_or(&0) != text.len() {
        cuts.push(text.len());
    }
    let mut new_spans = vec![];
    for w in cuts.windows(2) {
        for s in clip_spans(spans, w[0], w[1]) {
            new_spans.push(Span {
                start: map[s.start + w[0]],
                end: map[s.end + w[0]],
                ..s
            });
        }
    }
    (out, new_spans)
}

include!("rich_cells.rs");

/// `get_character_cell_size`
fn char_width(c: char) -> usize {
    let cp = c as u32;
    let (mut lo, mut hi) = (0usize, CELL_WIDTHS.len());
    while lo < hi {
        let mid = (lo + hi) / 2;
        let (start, end, width) = CELL_WIDTHS[mid];
        if cp < start {
            hi = mid;
        } else if cp > end {
            lo = mid + 1;
        } else {
            return if width < 0 { 0 } else { width as usize };
        }
    }
    1
}

fn cell_len(s: &[char]) -> usize {
    s.iter().map(|c| char_width(*c)).sum()
}

/// `set_cell_size` when cropping
fn set_cell_size(s: &[char], total: usize) -> Vec<char> {
    let mut out = vec![];
    let mut w = 0;
    for &c in s {
        let cw = char_width(c);
        if w + cw > total {
            break;
        }
        out.push(c);
        w += cw;
    }
    while w < total {
        out.push(' ');
        w += 1;
    }
    out
}

/// rich._wrap.divide_line(text, width, fold=True)
fn divide_line(text: &str, width: usize) -> Vec<usize> {
    let t: Vec<char> = text.chars().collect();
    let mut breaks = vec![];
    let mut cell_offset = 0usize;
    // words: re.match(r"\s*\S+\s*") repeatedly
    let mut pos = 0;
    loop {
        let mut k = pos;
        while k < t.len() && py_isspace(t[k]) {
            k += 1;
        }
        if k == t.len() {
            break;
        }
        while k < t.len() && !py_isspace(t[k]) {
            k += 1;
        }
        while k < t.len() && py_isspace(t[k]) {
            k += 1;
        }
        let mut start = pos;
        let word = &t[pos..k];
        pos = k;
        let trimmed_len = word
            .iter()
            .rposition(|c| !py_isspace(*c))
            .map_or(0, |p| p + 1);
        let word_length = cell_len(&word[..trimmed_len]);
        let remaining = width as isize - cell_offset as isize;
        if remaining >= word_length as isize {
            cell_offset += cell_len(word);
        } else if word_length > width {
            // fold: chop_cells(word, width)
            let mut lines: Vec<Vec<char>> = vec![vec![]];
            let mut total = 0;
            for &c in word {
                let cw = char_width(c);
                if total + cw > width {
                    lines.push(vec![c]);
                    total = cw;
                } else {
                    if let Some(l) = lines.last_mut() {
                        l.push(c);
                    }
                    total += cw;
                }
            }
            let count = lines.len();
            for (i, line) in lines.iter().enumerate() {
                if start != 0 {
                    breaks.push(start);
                }
                if i + 1 == count {
                    cell_offset = cell_len(line);
                } else {
                    start += line.len();
                }
            }
        } else if cell_offset != 0 && start != 0 {
            breaks.push(start);
            cell_offset = cell_len(word);
        }
    }
    breaks
}

#[cfg(test)]
mod tests {
    use super::*;

    fn plain(markup: &str, width: usize) -> String {
        let c = Console {
            diff: false,
            color_system: None,
            no_color: false,
            width,
        };
        let (p, _) = render_markup(markup).unwrap();
        let s: String = p.iter().collect();
        let mut out = vec![];
        for line in s.split('\n') {
            let offs = divide_line(line, c.width);
            let chars: Vec<char> = line.chars().collect();
            let mut b = vec![0];
            b.extend(offs);
            b.push(chars.len());
            for w in b.windows(2) {
                out.push(chars[w[0]..w[1]].iter().collect::<String>());
            }
        }
        out.join("\n")
    }

    #[test]
    fn markup_and_wrap() {
        assert_eq!(plain("[online]online[/online] x", 80), "online x");
        assert_eq!(plain("\\[x] [1] y", 80), "[x] [1] y");
        assert_eq!(
            plain(&"a ".repeat(50), 80),
            format!("{}\n{}", "a ".repeat(40), "a ".repeat(10))
        );
        assert!(render_markup("[/green] x").is_err());
    }

    #[test]
    fn highlighter() {
        let t: Vec<char> = "●  2: enp0s31f6 1.2.3.4/24 (dynamic) \"x\""
            .chars()
            .collect();
        let mut spans = vec![];
        highlight(&t, &mut spans);
        let got: Vec<(usize, usize)> = spans.iter().map(|s| (s.start, s.end)).collect();
        assert_eq!(got, vec![(3, 4), (24, 26), (37, 40)]);
    }
}
