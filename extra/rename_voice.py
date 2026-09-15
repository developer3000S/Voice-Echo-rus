import os
import glob
import re

files_to_update = glob.glob('*.py') + glob.glob('**/*.html', recursive=True)

pattern = re.compile(r'\bVoice(?:\s*AI(?:\s*-\s*Lite|\s*Lite)?)?\b(?!\s*Echo)', re.IGNORECASE)

def replacer(match):
    text = match.group(0)
    if text.isupper():
        return "VOICE ECHO"
    elif text.islower():
        return "voice echo"
    else:
        return "Voice Echo"

for file_path in files_to_update:
    if file_path == 'rename_voice.py':
        continue
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        new_content = pattern.sub(replacer, content)
        
        # Handle Hindi occurrences
        new_content = new_content.replace('वॉइस', 'वॉइस इको')
        # Clean up any potential accidental doubling
        new_content = new_content.replace('वॉइस इको इको', 'वॉइस इको')
        
        if new_content != content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Updated {file_path}")
            
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
