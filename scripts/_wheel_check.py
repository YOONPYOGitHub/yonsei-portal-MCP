import glob
import zipfile

w = sorted(glob.glob("dist/*.whl"))[-1]
print("WHEEL:", w)
names = zipfile.ZipFile(w).namelist()
for n in names:
    print("  ", n)
pem = [n for n in names if n.endswith(".pem")]
print("PEM INCLUDED:", pem)
assert pem, "intermediate .pem missing from wheel!"
print("OK")
