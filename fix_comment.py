with open('kokoro_studio/gui.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '    # worker, so the rate estimate from `idx == 0` is wildly inflated.'
new = '    # worker, so the rate estimate from `cumulative_chunk_count == 0` is\n    # wildly inflated.'

if old in content:
    content = content.replace(old, new)
    print('Comment updated')
else:
    print('Comment pattern not found')

with open('kokoro_studio/gui.py', 'w', encoding='utf-8') as f:
    f.write(content)
