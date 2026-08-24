"""Assemble a fully self-contained interactive HTML artwork.

The GLB is inlined as base64 and three.js is bundled in, so the page issues no
network request at all — it renders inside a sandboxed iframe with no external
origins, which is what an Arweave-hosted interactive HTML piece needs.
"""
import base64, os, sys

SP = os.environ.get("PEBBLECITY_BUILD_DIR", os.path.dirname(os.path.abspath(__file__)))
GLB = "/home/user/Sopulu11/pebblecity_animated.glb"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/user/Sopulu11/pebblecity_interactive.html"

glb_b64 = base64.b64encode(open(GLB, "rb").read()).decode("ascii")
bundle = open(f"{SP}/html/bundle.js").read()

html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>PebbleCity</title>
<style>
  html,body{margin:0;height:100%%;background:#000;overflow:hidden;
    -webkit-tap-highlight-color:transparent}
  canvas{display:block;width:100%%;height:100%%;touch-action:none}
  #status{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;
    color:#8b93a5;font:400 14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
    Helvetica,Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;
    pointer-events:none;transition:opacity .8s ease}
  #hint{position:fixed;left:50%%;bottom:18px;transform:translateX(-50%%);
    color:#5d6474;font:400 11px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
    Helvetica,Arial,sans-serif;letter-spacing:.16em;text-transform:uppercase;
    pointer-events:none;animation:fade 1.2s ease 6s forwards}
  @keyframes fade{to{opacity:0}}
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="status">Loading PebbleCity</div>
<div id="hint">Drag to look &nbsp;·&nbsp; scroll to zoom</div>
<script>window.__PEBBLECITY_GLB__=%s;</script>
<script>%s</script>
</body>
</html>
""" % ('"' + glb_b64 + '"', bundle)

open(OUT, "w", encoding="utf-8").write(html)
print(f"{OUT}  {os.path.getsize(OUT)/1e6:.2f} MB  (glb {len(glb_b64)/1e6:.2f} MB b64 + bundle {len(bundle)/1e6:.2f} MB)")
