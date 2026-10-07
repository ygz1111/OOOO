import re
raw = open("/home/wy/ai-projects/smart-grid/runs/logs/train_tf_v3.log", encoding="utf-8", errors="ignore").read()
lines = [l for l in raw.replace("\r", "\n").split("\n")
         if re.search(r"Epoch [0-9]+/150|val_loss|improved|windows:|TRAINING DONE|Traceback|Error", l)]
print("\n".join(lines[-12:]))
