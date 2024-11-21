# Re-creating the ASS subtitle file after environment reset

# Define the subtitle content with dynamic effects
subtitle_dynamic_content = """
[Script Info]
Title: Dynamic Karaoke Subtitle Example
ScriptType: v4.00+
Collisions: Normal
PlayDepth: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default, Arial, 60, &H00FFFFFF, &H00FFFFFF, &H00000000, &H00000000, -1, 0, 0, 0, 100, 100, 0, 0, 1, 3, 0, 2, 10, 10, 10, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:10.00,Default,,0,0,0,,{\k20\c&HFFFF00&\3c&HFF0000&}I {\k30\c&H00FF00&\3c&HFF0000&}hate {\k40\c&H0000FF&\3c&HFF0000&}UK {\k30\c&HFF00FF&\3c&HFF0000&}and {\k40\c&HFFFF00&\3c&HFF0000&}I {\k50\c&H00FFFF&\3c&HFF0000&}fucking {\k60\c&HFF0000&\3c&HFF00FF&}HaTe {\k50\c&HFFFF00&\3c&H00FF00&}Uk!! {\k60\c&HFF00FF&\3c&HFFFF00&}屌你老母個臭閪嘴~
"""

# Save the content to an ASS file
subtitle_dynamic_file_path = "dynamic_karaoke_subtitle_example.ass"
with open(subtitle_dynamic_file_path, "w") as f:
    f.write(subtitle_dynamic_content)

subtitle_dynamic_file_path
