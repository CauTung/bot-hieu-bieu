import os
import subprocess

def push_env():
    with open(".env") as f:
        lines = f.readlines()
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, val = line.split("=", 1)
        print(f"Adding {key}...")
        subprocess.run(f"vercel env rm {key} production preview development -y", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc = subprocess.Popen(f"vercel env add {key} production preview development", shell=True, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        proc.communicate(input=val)
    print("Done adding environment variables!")

if __name__ == "__main__":
    push_env()
