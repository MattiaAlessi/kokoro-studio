import sys
data = open(sys.argv[1], 'rb').read()
i = data.find(b'setPlaceholderText(')
chunk = data[i:i+600]
with open('_helpers/_placeholder_bytes.txt', 'wb') as f:
    f.write(chunk)
print("Wrote 600 bytes starting at setPlaceholderText")
print(f"Length: {len(chunk)}")
