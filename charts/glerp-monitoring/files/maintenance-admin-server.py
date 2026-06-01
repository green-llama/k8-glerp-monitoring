#!/usr/bin/env python3
"""
GLerp Maintenance Window Admin
Create / list / delete maintenance windows.
Each window writes a VictoriaMetrics metric, a Grafana annotation, and an
AlertManager silence.  Deletion expires the silence, removes the VM samples,
and permanently deletes the Grafana annotation (blue band removed from dashboards).
"""
import base64
import html
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

VM_URL        = os.environ.get("VM_URL",        "http://localhost:8428")
GRAFANA_URL   = os.environ.get("GRAFANA_URL",   "http://localhost:3000")
GRAFANA_TOKEN = os.environ.get("GRAFANA_TOKEN", "")
AM_URL        = os.environ.get("AM_URL",        "http://localhost:9093")
ADMIN_USER    = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASS    = os.environ.get("ADMIN_PASSWORD", "changeme")

METRIC_WINDOW  = "glerp_maintenance_window"
METRIC_EXCUSED = "glerp_maintenance_excused_failures"

# ── HTML ─────────────────────────────────────────────────────────────────────

PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GLerp Maintenance Admin</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:sans-serif;max-width:980px;margin:40px auto;padding:0 20px;color:#333}}
h1{{color:#27B093;margin-bottom:4px}}
h2{{margin-top:0;font-size:1.05rem;color:#555}}
.card{{background:#f7f8fa;border:1px solid #dde;border-radius:6px;padding:20px;margin:24px 0}}
label{{display:block;margin:12px 0 4px;font-weight:600;font-size:.9rem}}
input,select{{width:100%;padding:8px 10px;border:1px solid #ccc;border-radius:4px;font-size:.95rem}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.btn{{display:inline-block;padding:8px 20px;border:none;border-radius:4px;cursor:pointer;font-size:.9rem;color:#fff}}
.btn-blue{{background:#27B093}}.btn-blue:hover{{background:#00534C}}
.btn-red{{background:#dc3545}}.btn-red:hover{{background:#b02a37}}
.btn-grey{{background:#2B5B6C}}.btn-grey:hover{{background:#072B31}}
.msg{{padding:12px 16px;border-radius:4px;margin-bottom:16px}}
.ok{{background:#E3F5F2;border:1px solid #27B093}}
.err{{background:#f8d7da;border:1px solid #dc3545}}
.info{{background:#E3F5F2;border:1px solid #27B093}}
table{{width:100%;border-collapse:collapse;font-size:.84rem;margin-top:8px}}
th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid #ddd;vertical-align:top}}
th{{background:#D1E0D7;font-size:.8rem}}
.s-active{{color:#27B093;font-weight:700}}
.s-upcoming{{color:#fd7e14;font-weight:700}}
.s-past{{color:#6c757d}}
.del-panel{{display:none;margin-top:8px;padding:10px;background:#fff3cd;
             border:1px solid #ffc107;border-radius:4px}}
.del-panel input{{margin-bottom:8px}}
.note{{font-size:.8rem;color:#777;margin-top:6px}}
.tz{{font-size:.8rem;color:#27B093;margin-top:4px}}
</style>
<script>
document.addEventListener("DOMContentLoaded",function(){{
  var rawOff=new Date().getTimezoneOffset();
  var tzField=document.getElementById("tz_offset");
  if(tzField) tzField.value=rawOff;
  var off=-rawOff;
  var sign=off>=0?"+":"-";
  var h=String(Math.floor(Math.abs(off)/60)).padStart(2,"0");
  var m=String(Math.abs(off)%60).padStart(2,"0");
  var tzStr="UTC"+sign+h+":"+m;
  var el=document.getElementById("tzinfo");
  if(el){{
    el.textContent="Browser timezone: "+tzStr+
      " — enter times in your local time, the server converts to UTC automatically.";
  }}
  var pad=function(n){{return String(n).padStart(2,"0");}};
  document.querySelectorAll(".local-time").forEach(function(span){{
    var ms=parseInt(span.getAttribute("data-ms"),10);
    if(!isNaN(ms)){{
      var d=new Date(ms);
      span.textContent=d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate())+
        " "+pad(d.getHours())+":"+pad(d.getMinutes())+" ("+tzStr+")";
    }}
  }});
}});
function showDel(id){{document.getElementById("del-"+id).style.display="block";}}
function hideDel(id){{document.getElementById("del-"+id).style.display="none";}}
</script>
</head>
<body>
<div style="margin-bottom:12px"><img src="data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyBpZD0iTG9nb19BcnR3b3JrIiBkYXRhLW5hbWU9IkxvZ28gQXJ0d29yayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwIDAgMTc3LjczIDEwNi43MyI+CiAgPGRlZnM+CiAgICA8c3R5bGU+CiAgICAgIC5jbHMtMSB7CiAgICAgICAgZmlsbDogIzI3YjA5MzsKICAgICAgfQoKICAgICAgLmNscy0yIHsKICAgICAgICBmaWxsOiAjMmEyYjJhOwogICAgICB9CiAgICA8L3N0eWxlPgogIDwvZGVmcz4KICA8Zz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTEwNy4zOSw0NS4zNmMtLjUzLTEuMDItMS4yNi0xLjc5LTIuMjEtMi4zMS0uOTQtLjUyLTIuMDMtLjc4LTMuMjYtLjc4LTEuMzUsMC0yLjU2LjMtMy42Mi45MS0xLjA2LjYxLTEuODksMS40Ny0yLjQ4LDIuNTktLjYsMS4xMi0uOSwyLjQxLS45LDMuODhzLjMsMi43Ny45LDMuOWMuNiwxLjEzLDEuNDMsMS45OSwyLjQ4LDIuNiwxLjA2LjYxLDIuMjYuOTEsMy42Mi45MSwxLjgyLDAsMy4zLS41MSw0LjQ0LTEuNTMsMS4xNC0xLjAyLDEuODMtMi40LDIuMDktNC4xNWgtNy42OHYtMi42OGgxMS4yNnYyLjYyYy0uMjIsMS41OS0uNzgsMy4wNS0xLjY5LDQuMzgtLjkxLDEuMzMtMi4xLDIuNC0zLjU2LDMuMTktMS40Ni43OS0zLjA4LDEuMTktNC44NywxLjE5LTEuOTIsMC0zLjY4LS40NS01LjI2LTEuMzQtMS41OS0uODktMi44NS0yLjEzLTMuNzgtMy43Mi0uOTMtMS41OS0xLjQtMy4zOC0xLjQtNS4zOHMuNDctMy43OSwxLjQtNS4zOGMuOTMtMS41OSwyLjItMi44MywzLjc5LTMuNzIsMS42LS44OSwzLjM1LTEuMzQsNS4yNS0xLjM0LDIuMTgsMCw0LjExLjUzLDUuODEsMS42LDEuNywxLjA3LDIuOTMsMi41OCwzLjY5LDQuNTRoLTQuMDNaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xMjAuNjQsNDQuMTRjLjgxLS40NiwxLjc4LS42OSwyLjktLjY5djMuNDdoLS44NWMtMS4zMSwwLTIuMzEuMzMtMi45OCwxLS42OC42Ny0xLjAxLDEuODItMS4wMSwzLjQ3djguNTNoLTMuMzV2LTE2LjJoMy4zNXYyLjM1Yy40OS0uODIsMS4xNC0xLjQ3LDEuOTYtMS45M1oiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTE0MS4zNiw1My4wNmgtMTIuMzhjLjEsMS4yOS41OCwyLjMzLDEuNDQsMy4xMi44Ni43OCwxLjkyLDEuMTgsMy4xOCwxLjE4LDEuOCwwLDMuMDgtLjc1LDMuODItMi4yNmgzLjYyYy0uNDksMS40OS0xLjM4LDIuNzEtMi42NiwzLjY2LTEuMjguOTUtMi44OCwxLjQzLTQuNzgsMS40My0xLjU1LDAtMi45NC0uMzUtNC4xNi0xLjA0LTEuMjMtLjctMi4xOS0xLjY4LTIuODgtMi45NC0uNy0xLjI2LTEuMDQtMi43My0xLjA0LTQuNHMuMzQtMy4xMywxLjAxLTQuNCwxLjYzLTIuMjQsMi44NS0yLjkzYzEuMjMtLjY5LDIuNjMtMS4wMyw0LjIyLTEuMDNzMi44OS4zMyw0LjA5LDFjMS4yLjY3LDIuMTMsMS42LDIuNzksMi44MS42NywxLjIxLDEsMi41OSwxLDQuMTYsMCwuNjEtLjA0LDEuMTYtLjEyLDEuNjVaTTEzNy45Nyw1MC4zNmMtLjAyLTEuMjQtLjQ2LTIuMjMtMS4zMi0yLjk3LS44Ni0uNzQtMS45My0xLjEyLTMuMjEtMS4xMi0xLjE2LDAtMi4xNS4zNy0yLjk3LDEuMS0uODIuNzQtMS4zMSwxLjczLTEuNDcsMi45OGg4Ljk3WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTU5LjUsNTMuMDZoLTEyLjM4Yy4xLDEuMjkuNTgsMi4zMywxLjQ0LDMuMTIuODYuNzgsMS45MiwxLjE4LDMuMTgsMS4xOCwxLjgsMCwzLjA4LS43NSwzLjgyLTIuMjZoMy42MmMtLjQ5LDEuNDktMS4zOCwyLjcxLTIuNjYsMy42Ni0xLjI4Ljk1LTIuODgsMS40My00Ljc4LDEuNDMtMS41NSwwLTIuOTQtLjM1LTQuMTYtMS4wNC0xLjIzLS43LTIuMTktMS42OC0yLjg4LTIuOTQtLjctMS4yNi0xLjA0LTIuNzMtMS4wNC00LjRzLjM0LTMuMTMsMS4wMS00LjQsMS42My0yLjI0LDIuODUtMi45M2MxLjIzLS42OSwyLjYzLTEuMDMsNC4yMi0xLjAzczIuODkuMzMsNC4wOSwxYzEuMi42NywyLjEzLDEuNiwyLjc5LDIuODEuNjcsMS4yMSwxLDIuNTksMSw0LjE2LDAsLjYxLS4wNCwxLjE2LS4xMiwxLjY1Wk0xNTYuMTIsNTAuMzZjLS4wMi0xLjI0LS40Ni0yLjIzLTEuMzItMi45Ny0uODYtLjc0LTEuOTMtMS4xMi0zLjIxLTEuMTItMS4xNiwwLTIuMTUuMzctMi45NywxLjFzLTEuMzEsMS43My0xLjQ3LDIuOThoOC45N1oiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTE3NC41MSw0NC4yNGMxLjAxLjUzLDEuOCwxLjMxLDIuMzcsMi4zNS41NywxLjA0Ljg1LDIuMjkuODUsMy43NnY5LjU2aC0zLjMydi05LjA2YzAtMS40NS0uMzYtMi41Ni0xLjA5LTMuMzQtLjczLS43Ny0xLjcyLTEuMTYtMi45Ny0xLjE2cy0yLjI1LjM5LTIuOTgsMS4xNmMtLjc0Ljc3LTEuMSwxLjg5LTEuMSwzLjM0djkuMDZoLTMuMzV2LTE2LjJoMy4zNXYxLjg1Yy41NS0uNjcsMS4yNS0xLjE5LDIuMS0xLjU2Ljg1LS4zNywxLjc2LS41NiwyLjcyLS41NiwxLjI3LDAsMi40Mi4yNiwzLjQzLjc5WiIvPgogIDwvZz4KICA8Zz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTk1LjY4LDgzLjE3aDYuNTl2My4xOGgtMTAuNnYtMjBoNC4wMXYxNi44MloiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTEwOC44Myw2Ni4zOHYxOS45N2gtNC4wMXYtMTkuOTdoNC4wMVoiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTExMi43Miw3NC4wOWMuNjQtMS4yNCwxLjUxLTIuMiwyLjYxLTIuODYsMS4xLS42NywyLjMzLTEsMy42OC0xLDEuMTgsMCwyLjIyLjI0LDMuMTEuNzIuODkuNDgsMS42LDEuMDgsMi4xMywxLjh2LTIuMjZoNC4wNHYxNS44N2gtNC4wNHYtMi4zMmMtLjUyLjc0LTEuMjMsMS4zNi0yLjEzLDEuODUtLjkxLjQ5LTEuOTUuNzMtMy4xNC43My0xLjM0LDAtMi41NS0uMzQtMy42NS0xLjAzLTEuMS0uNjktMS45Ny0xLjY2LTIuNjEtMi45MS0uNjQtMS4yNS0uOTYtMi42OS0uOTYtNC4zMXMuMzItMy4wMy45Ni00LjI3Wk0xMjMuNjcsNzUuOTFjLS4zOC0uNy0uOS0xLjIzLTEuNTUtMS42cy0xLjM1LS41Ni0yLjA5LS41Ni0xLjQzLjE4LTIuMDYuNTRjLS42My4zNi0xLjE0Ljg5LTEuNTMsMS41OS0uMzkuNy0uNTksMS41Mi0uNTksMi40OHMuMiwxLjc5LjU5LDIuNTFjLjM5LjcyLjkxLDEuMjcsMS41NSwxLjY1LjY0LjM4LDEuMzIuNTcsMi4wNS41N3MxLjQ0LS4xOSwyLjA5LS41NiwxLjE2LS45MSwxLjU1LTEuNmMuMzgtLjcuNTctMS41My41Ny0yLjUxcy0uMTktMS44MS0uNTctMi41MVoiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTE1Ni42Myw3Mi4wNGMxLjE5LDEuMTksMS43OSwyLjg2LDEuNzksNXY5LjMxaC00LjAxdi04Ljc3YzAtMS4yNC0uMzItMi4xOS0uOTUtMi44NS0uNjMtLjY2LTEuNDktLjk5LTIuNTgtLjk5cy0xLjk1LjMzLTIuNTkuOTktLjk2LDEuNjEtLjk2LDIuODV2OC43N2gtNC4wMXYtOC43N2MwLTEuMjQtLjMxLTIuMTktLjk1LTIuODUtLjYzLS42Ni0xLjQ5LS45OS0yLjU4LS45OXMtMS45OC4zMy0yLjYyLjk5LS45NiwxLjYxLS45NiwyLjg1djguNzdoLTQuMDF2LTE1Ljg3aDQuMDF2MS45MmMuNTItLjY3LDEuMTgtMS4xOSwxLjk5LTEuNTguODEtLjM4LDEuNy0uNTcsMi42OC0uNTcsMS4yNCwwLDIuMzUuMjYsMy4zMi43OXMxLjczLDEuMjcsMi4yNiwyLjI1Yy41Mi0uOTIsMS4yNy0xLjY1LDIuMjUtMi4yMS45OC0uNTUsMi4wNS0uODMsMy4xOS0uODMsMS45NSwwLDMuNTIuNiw0LjcxLDEuNzlaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xNjIuMTYsNzQuMDljLjY0LTEuMjQsMS41MS0yLjIsMi42MS0yLjg2LDEuMS0uNjcsMi4zMy0xLDMuNjgtMSwxLjE4LDAsMi4yMi4yNCwzLjExLjcyLjg5LjQ4LDEuNiwxLjA4LDIuMTMsMS44di0yLjI2aDQuMDR2MTUuODdoLTQuMDR2LTIuMzJjLS41Mi43NC0xLjIzLDEuMzYtMi4xMywxLjg1LS45MS40OS0xLjk1LjczLTMuMTQuNzMtMS4zNCwwLTIuNTUtLjM0LTMuNjUtMS4wMy0xLjEtLjY5LTEuOTctMS42Ni0yLjYxLTIuOTEtLjY0LTEuMjUtLjk2LTIuNjktLjk2LTQuMzFzLjMyLTMuMDMuOTYtNC4yN1pNMTczLjEyLDc1LjkxYy0uMzgtLjctLjktMS4yMy0xLjU1LTEuNnMtMS4zNS0uNTYtMi4wOS0uNTYtMS40My4xOC0yLjA2LjU0Yy0uNjMuMzYtMS4xNC44OS0xLjUzLDEuNTktLjM5LjctLjU5LDEuNTItLjU5LDIuNDhzLjIsMS43OS41OSwyLjUxYy4zOS43Mi45MSwxLjI3LDEuNTUsMS42NS42NC4zOCwxLjMyLjU3LDIuMDUuNTdzMS40NC0uMTksMi4wOS0uNTYsMS4xNi0uOTEsMS41NS0xLjZjLjM4LS43LjU3LTEuNTMuNTctMi41MXMtLjE5LTEuODEtLjU3LTIuNTFaIi8+CiAgPC9nPgogIDxnPgogICAgPGc+CiAgICAgIDxnPgogICAgICAgIDxwYXRoIGNsYXNzPSJjbHMtMSIgZD0iTTY1LjQ1LDcxLjA2Yy0uMDUtLjQxLS4wOC0uODItLjE4LTEuMjItLjMyLTEuNC0uODQtMi43My0xLjU3LTMuOTYtLjMxLS41Mi0uNjQtMS4wMi0uOTUtMS41NGwtLjM4LjI1Yy0uOTEuNzYtMS45MSwxLjQxLTIuOTcsMS45NC4wNi4wOC4xMi4xNC4xNS4yMS4xOC4zNS4zOC43LjUzLDEuMDYuNzUsMS43NiwxLjI3LDMuNTgsMS40MSw1LjUxLjEyLDEuNjUsMCwzLjI3LS40OCw0Ljg1LS40MywxLjQzLTEuMTcsMi43LTIuMDksMy44Ny0uMDQuMDUtLjA5LjA4LS4xNS4xMi0uMS0uMDgtLjE4LS4xNS0uMjctLjIzLS42OS0uNjEtMS4zOC0xLjIyLTIuMDctMS44My0uNTctLjQ5LTEuMTMtLjk4LTEuNzItMS40Ni4xMi44Ni40MSwxLjczLjY4LDIuNTYuMTguNTYuMzksMS4xMS42MywxLjY0cy40NywxLjA2Ljc2LDEuNTVjLjMyLjU1LjY0LDEuMS45NiwxLjY0LDEuMTIsMS44NywxLjY1LDMuOTEsMS42Myw2LjA4LDAsLjY1LS4wNCwxLjMtLjE3LDEuOTQtLjE2Ljc4LS4zOSwxLjU0LS42OCwyLjI4LS4yOC43MS0uNjQsMS4zOC0xLjA5LDItLjA0LjA2LS4xLjEtLjE2LjE3LS4wNC0uMDctLjA4LS4xLS4wOS0uMTUtLjMtLjk3LS43NC0xLjg5LTEuMjQtMi43OC0uMzgtLjY4LS43OS0xLjMzLTEuMzEtMS45MnMtMS4wNS0xLjE3LTEuNjItMS43Yy0uMDItLjAyLS4wNS0uMDQtLjA3LS4wNi0uMDUtLjA0LS4wOS0uMDgtLjE0LS4xMi0uMDMtLjAzLS4xMi0uMTItLjE2LS4xMi0uMDYtLjA0LS4xNi0uMTQtLjIzLS4xNC4wNC4wOC4xLjE1LjE1LjIzLjE1LjI5LjMxLjU3LjQ2Ljg3cy4zLjU5LjQ0Ljg5Yy4yMi40Ni40Ljk0LjU1LDEuNDIuMjYuODMuNDQsMS42OC41OCwyLjU1LjEyLjcyLjE5LDEuNDQuMjcsMi4xNy4wNC40Mi4wOC44NS4xMiwxLjIyLjMyLjMyLjYyLjU4Ljg4Ljg4LjQ1LjUyLjc5LDEuMTEsMS4wOSwxLjcyLjQyLjg2Ljc2LDEuNzUuOTUsMi42OC4xLjU0LjE1LjUzLjY5LjU0LDEuMTEuMDEsMi4yMi4wMywzLjMzLjA0LjE2LDAsLjMyLDAsLjQ4LS4wMS4xMy0uMDEuMi0uMS4xOC0uMjMtLjA1LS4yOC0uMDgtLjU3LS4xNS0uODQtLjMzLTEuMzYtLjc2LTIuNjktMS40MS0zLjkzLS4yOS0uNTYtLjU5LTEuMTItLjkxLTEuNjctLjEtLjE4LS4xLS4zMi4wNC0uNDcuMjItLjI1LjQzLS41MS42NC0uNzcsMS4wMS0xLjI0LDEuNzktMi42MSwyLjI3LTQuMTUuMjktLjkzLjQ3LTEuODcuNDktMi44NS4wMi0xLjAzLS4wNS0yLjA2LS4yNS0zLjA3LS4xNy0uODktLjQzLTEuNzUtLjc2LTIuNi0uMzctLjk3LS44Ni0xLjg4LTEuMzgtMi43Ny0uMDUtLjA5LS4wOS0uMTktLjEzLS4yOS4wNi0uMDcuMS0uMTEuMTQtLjE2Ljg3LS45MSwxLjY1LTEuODksMi4zMi0yLjk1LjY4LTEuMDksMS4yOC0yLjIzLDEuNjMtMy40OC4xLS4zOC4xOC0uNzcuMjctMS4xNi4yMi0uOTUuMjQtMS45Mi4yMi0yLjg5LS4wMS0uNDYtLjA5LS45MS0uMTQtMS4zN1oiLz4KICAgICAgICA8cGF0aCBjbGFzcz0iY2xzLTEiIGQ9Ik0zLjA3LDcxLjA2Yy4wNS0uNDEuMDgtLjgyLjE4LTEuMjIuMzItMS40Ljg0LTIuNzMsMS41Ny0zLjk2LjMxLS41Mi42NC0xLjAyLjk1LTEuNTRsLjM4LjI1Yy45MS43NiwxLjkxLDEuNDEsMi45NywxLjk0LS4wNi4wOC0uMTIuMTQtLjE1LjIxLS4xOC4zNS0uMzguNy0uNTMsMS4wNi0uNzUsMS43Ni0xLjI3LDMuNTgtMS40MSw1LjUxLS4xMiwxLjY1LDAsMy4yNy40OCw0Ljg1LjQzLDEuNDMsMS4xNywyLjcsMi4wOSwzLjg3LjA0LjA1LjA5LjA4LjE1LjEyLjEtLjA4LjE4LS4xNS4yNy0uMjMuNjktLjYxLDEuMzgtMS4yMiwyLjA3LTEuODMuNTctLjQ5LDEuMTMtLjk4LDEuNzItMS40Ni0uMTIuODYtLjQxLDEuNzMtLjY4LDIuNTYtLjE4LjU2LS4zOSwxLjExLS42MywxLjY0cy0uNDcsMS4wNi0uNzYsMS41NWMtLjMyLjU1LS42NCwxLjEtLjk2LDEuNjQtMS4xMiwxLjg3LTEuNjUsMy45MS0xLjYzLDYuMDgsMCwuNjUuMDQsMS4zLjE3LDEuOTQuMTYuNzguMzksMS41NC42OCwyLjI4LjI4LjcxLjY0LDEuMzgsMS4wOSwyLC4wNC4wNi4xLjEuMTYuMTcuMDQtLjA3LjA4LS4xLjA5LS4xNS4zLS45Ny43NC0xLjg5LDEuMjQtMi43OC4zOC0uNjguNzktMS4zMywxLjMxLTEuOTJzMS4wNS0xLjE3LDEuNjItMS43Yy4wMi0uMDIuMDUtLjA0LjA3LS4wNi4wNS0uMDQuMDktLjA4LjE0LS4xMi4wMy0uMDMuMTItLjEyLjE2LS4xMi4wNi0uMDQuMTYtLjE0LjIzLS4xNC0uMDQuMDgtLjEuMTUtLjE1LjIzLS4xNS4yOS0uMzEuNTctLjQ2Ljg3cy0uMy41OS0uNDQuODljLS4yMi40Ni0uNC45NC0uNTUsMS40Mi0uMjYuODMtLjQ0LDEuNjgtLjU4LDIuNTUtLjEyLjcyLS4xOSwxLjQ0LS4yNywyLjE3LS4wNC40Mi0uMDguODUtLjEyLDEuMjItLjMyLjMyLS42Mi41OC0uODguODgtLjQ1LjUyLS43OSwxLjExLTEuMDksMS43Mi0uNDIuODYtLjc2LDEuNzUtLjk1LDIuNjgtLjEuNTQtLjE1LjUzLS42OS41NC0xLjExLjAxLTIuMjIuMDMtMy4zMy4wNC0uMTYsMC0uMzIsMC0uNDgtLjAxLS4xMy0uMDEtLjItLjEtLjE4LS4yMy4wNS0uMjguMDgtLjU3LjE1LS44NC4zMy0xLjM2Ljc2LTIuNjksMS40MS0zLjkzLjI5LS41Ni41OS0xLjEyLjkxLTEuNjcuMS0uMTguMS0uMzItLjA0LS40Ny0uMjItLjI1LS40My0uNTEtLjY0LS43Ny0xLjAxLTEuMjQtMS43OS0yLjYxLTIuMjctNC4xNS0uMjktLjkzLS40Ny0xLjg3LS40OS0yLjg1LS4wMi0xLjAzLjA1LTIuMDYuMjUtMy4wNy4xNy0uODkuNDMtMS43NS43Ni0yLjYuMzctLjk3Ljg2LTEuODgsMS4zOC0yLjc3LjA1LS4wOS4wOS0uMTkuMTMtLjI5LS4wNi0uMDctLjEtLjExLS4xNC0uMTYtLjg3LS45MS0xLjY1LTEuODktMi4zMi0yLjk1LS42OC0xLjA5LTEuMjgtMi4yMy0xLjYzLTMuNDgtLjEtLjM4LS4xOC0uNzctLjI3LTEuMTYtLjIyLS45NS0uMjQtMS45Mi0uMjItMi44OS4wMS0uNDYuMDktLjkxLjE0LTEuMzdaIi8+CiAgICAgIDwvZz4KICAgICAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNNDcuNTEsNzUuNzljMC0uMDYsMC0uMTIsMC0uMTgsMC0uMTYtLjAyLS4zMi0uMDUtLjQ4LS4wMi0uMTYtLjA0LS4zMy0uMDUtLjQ5LDAtLjA5LS4wMi0uMTgtLjAzLS4yOC0uMDMtLjI1LS4wOC0uNTEtLjE0LS43Ni0uMDktLjM0LS4xNi0uNjktLjIzLTEuMDQtLjA3LS4zNS0uMTQtLjctLjIzLTEuMDRsLS4wNC0uMTRjLS4yNi0xLS41My0yLjA0LS42Ny0zLjA4LS4wNi0uNDQtLjEtLjg4LS4xNC0xLjMzbC0uMDMtLjMzaC4wNWMtLjEtLjA2LS4yLS4xMi0uMzEtLjE3LS43LS4zNS0xLjM2LS43Ni0xLjk5LTEuMjEtLjA3LS4wNS0uMTQtLjEtLjIxLS4xNS0uMDIuNDItLjAzLjg2LS4wMSwxLjMuMDEuNTQuMDQsMS4xMy4xNSwxLjcuMDQuMi4wNi40MS4wOC42Mi4wMy4yNC4wNS40Ny4xLjcuMTIuNTguMjYsMS4xNy40LDEuNzNsLjIuOGMuMi44Mi40MSwxLjY2LjUyLDIuNS4xLjc2LjE2LDEuNTYtLjA1LDIuMzUtLjE5LjcxLS42LDEuMjgtMS4yMSwxLjcxLS4wMi4wMS0uMDQuMDMtLjA2LjA0LS4wNy4wNS0uMTMuMS0uMi4xNS0uNDkuMzMtMS4wNi41NS0xLjcuNjgsMCwwLDAsMC0uMDEsMC0uNTguMTQtMS4yLjIxLTEuODEuMTktLjgzLS4wMy0xLjU5LS4xOS0yLjI1LS41LS42MS0uMjgtMS4xNi0uNjYtMS42My0xLjE0LS4wOC0uMDktLjE1LS4xNy0uMTktLjI3LDAsMCwwLDAsMCwwLDAsMCwwLDAsMCwwLS4wMi0uMDMtLjAzLS4wNy0uMDMtLjExLS4wMi0uMDYtLjAzLS4xMy0uMDMtLjIsMC0uMDQsMC0uMDksMC0uMTN2LS4xMWMwLS4zMy0uMDItLjY4LS4wNC0xLjAyLS4wNS0xLjA0LS4xLTIuMTEuMjUtMy4wMi4zNC0uODcsMS4yLTEuNiwyLjA3LTIuMDguMTItLjA4LjI0LS4xNi4zNi0uMjQsMS4zNy0uOTMsMi43OC0xLjg5LDIuNzQtMy43MiwwLS4xNi0uMDItLjMyLS4wNS0uNDYtLjA5LS40Ni0uMy0uNzktLjY0LTEtMS4xMi0uNjgtMy4yMS4zNC00LjM0Ljg5bC0uMjIuMTFjLS41Mi4yNS0xLjA0LjUtMS41Ny41OS0uNTMtLjA5LTEuMDUtLjM0LTEuNTctLjU5bC0uMjItLjExYy0xLjEzLS41NS0zLjIyLTEuNTctNC4zNC0uODktLjM0LjIxLS41NS41NC0uNjQsMS0uMDMuMTQtLjA0LjI5LS4wNS40Ni0uMDQsMS44NCwxLjM3LDIuOCwyLjc0LDMuNzIuMTIuMDguMjQuMTYuMzYuMjQuODcuNDksMS43MywxLjIxLDIuMDcsMi4wOC4zNi45Mi4zLDEuOTkuMjUsMy4wMi0uMDIuMzUtLjAzLjY5LS4wNCwxLjAydi4xMXMwLC4wOSwwLC4xM2MwLC4wNy0uMDEuMTQtLjAzLjIsMCwuMDQtLjAyLjA4LS4wMy4xMSwwLDAsMCwwLDAsMCwwLDAsMCwwLDAsMC0uMDQuMDktLjEuMTgtLjE5LjI3LS40Ny40OC0xLjAyLjg2LTEuNjMsMS4xNC0uNjYuMy0xLjQyLjQ3LTIuMjUuNS0uNjIuMDItMS4yMy0uMDQtMS44MS0uMTksMCwwLDAsMC0uMDEsMC0uNjQtLjEzLTEuMjEtLjM1LTEuNy0uNjgtLjA3LS4wNS0uMTQtLjEtLjItLjE1LS4wMi0uMDEtLjA0LS4wMy0uMDYtLjA0LS42MS0uNDMtMS4wMi0xLjAxLTEuMjEtMS43MS0uMjEtLjc5LS4xNS0xLjYtLjA1LTIuMzUuMTEtLjg0LjMyLTEuNjguNTItMi41bC4yLS44Yy4xNC0uNTcuMjgtMS4xNS40LTEuNzMuMDUtLjIzLjA3LS40Ny4xLS43LjAyLS4yMS4wNS0uNDEuMDgtLjYyLjExLS41OC4xNC0xLjE2LjE1LTEuNy4wMS0uNDQsMC0uODgtLjAxLTEuMy0uMDcuMDUtLjE0LjEtLjIxLjE1LS42My40NS0xLjI5Ljg2LTEuOTksMS4yMS0uMS4wNS0uMi4xMS0uMzEuMTZoLjA1cy0uMDMuMzUtLjAzLjM1Yy0uMDQuNDQtLjA4Ljg5LS4xNCwxLjMzLS4xNCwxLjA0LS40MSwyLjA4LS42NywzLjA4bC0uMDQuMTRjLS4wOS4zNC0uMTYuNjktLjIzLDEuMDQtLjA3LjM1LS4xNC43LS4yMywxLjA0LS4wNy4yNS0uMTEuNTEtLjE0Ljc2LDAsLjA5LS4wMi4xOS0uMDMuMjgtLjAxLjE2LS4wMy4zMy0uMDUuNDktLjAyLjE2LS4wNC4zMi0uMDUuNDgsMCwuMDYsMCwuMTIsMCwuMTgsMCwuMTEsMCwuMjMsMCwuMzQsMCwuMDMsMCwuMDYsMCwuMSwwLC4xNS4wMi4zLjAzLjQ1LjAyLjE1LjA0LjI5LjA3LjQ0LjEzLjY4LjMzLDEuMjcuNiwxLjc4LjA5LjE4LjIuMzUuMzEuNTEsMCwwLDAsMCwwLC4wMS4xLjE0LjIxLjI4LjMyLjQyLjAyLjAzLjA1LjA1LjA3LjA4LjA1LjA2LjExLjEyLjE2LjE4LjIyLjIyLjQ2LjQ0LjcyLjY0LjQ1LjM0LjkxLjYyLDEuMzkuODVsLjA2LjIxYy4wMi4wNy4wNC4xMy4wNi4xOS4xMS4yMy4yMi40NS4zNC42Ny40Ni43OS45OSwxLjU5LDEuNjUsMi4zLDEuMjIsMS4zLDIuNjYsMi4yMSw0LjI5LDIuNzIsMS4wMy4zMiwyLjA5LjQ5LDMuMTUuNDksMS4wNiwwLDIuMTEtLjE3LDMuMTUtLjQ5LDEuNjMtLjUxLDMuMDctMS40Myw0LjI5LTIuNzIuNjYtLjcxLDEuMTktMS41MSwxLjY1LTIuMy4xMi0uMjIuMjQtLjQ0LjM0LS42Ny4wMy0uMDYuMDUtLjEyLjA2LS4xOWwuMDYtLjIxYy40OC0uMjMuOTUtLjUyLDEuMzktLjg1LjI2LS4yLjUtLjQxLjcyLS42NC4wNi0uMDYuMTEtLjEyLjE2LS4xNy4wMi0uMDMuMDUtLjA1LjA3LS4wOC4xMi0uMTQuMjItLjI3LjMyLS40MiwwLDAsMCwwLDAtLjAxLjEyLS4xNy4yMi0uMzQuMzEtLjUxLjI3LS41MS40Ny0xLjEuNi0xLjc4LjAzLS4xNC4wNS0uMjkuMDctLjQ0LjAyLS4xNS4wMy0uMy4wMy0uNDUsMC0uMDMsMC0uMDYsMC0uMSwwLS4xMiwwLS4yMywwLS4zNFpNMzguMDEsODQuNDdjLS41OS4zMS0xLjI0LjU0LTEuOTkuNzItLjIzLjA1LS40OS4wNy0uNzEuMDktLjA5LDAtLjE3LjAxLS4yNi4wMi0uMDEsMC0uMDIsMC0uMDMsMC0uMDUsMC0uMTEsMC0uMTYsMC0uMSwwLS4yLDAtLjMxLjAxLS4wMSwwLS4wMywwLS4wNCwwLS4wOCwwLS4xNiwwLS4yNSwwLS4wOCwwLS4xNywwLS4yNSwwLS4wMSwwLS4wMywwLS4wNCwwLS4xLDAtLjIxLDAtLjMxLS4wMS0uMDUsMC0uMTEsMC0uMTYsMC0uMDEsMC0uMDIsMC0uMDMsMC0uMDksMC0uMTcsMC0uMjYtLjAyLS4yMi0uMDItLjQ4LS4wMy0uNzEtLjA5LS43NS0uMTgtMS40LS40MS0xLjk5LS43Mi0uOTktLjUxLTEuNzUtMS4yMS0yLjM0LTIuMDgsMS4xNC4wMywyLjExLS4xMSwzLS40Mi43Ny0uMjcsMS40Ny0uNjMsMi4xMS0xLjA3LjI4LS4yLjU0LS40My43OC0uNjYuMDUtLjA1LjExLS4xLjE3LS4xNS4wMSwwLC4wMi4wMi4wMy4wMy4wMSwwLC4wMi0uMDIuMDMtLjAzLjA2LjA1LjExLjEuMTcuMTUuMjQuMjQuNS40Ni43OC42Ni42NC40NCwxLjM0LjgsMi4xMSwxLjA3Ljg5LjMyLDEuODUuNDUsMywuNDItLjU5Ljg4LTEuMzYsMS41Ny0yLjM0LDIuMDhaIi8+CiAgICAgIDxwYXRoIGNsYXNzPSJjbHMtMSIgZD0iTTY3LjYzLDUwLjdoLTEuNjhjLS4wNS0uMzMtLjEyLS42Ni0uMi0uOTgtMS4wNi00LjM2LTQuMjMtNy44Ny04LjM3LTkuNDMtLjk0LS4zNS0xLjk0LS42MS0yLjk3LS43NC0uNi0uMDgtMS4yLS4xMi0xLjgyLS4xMi01LjI1LDAtOS44MiwzLjAxLTEyLjA0LDcuNDItLjE0LjI3LS4yNy41NS0uMzkuODMtLjQ2LS4zNy0uOTYtLjY3LTEuNDctLjkxLTIuMTQtMS00LjQyLS45Ny00LjQyLS45NywwLDAtMi4yOC0uMDMtNC40Mi45Ny0uNTEuMjQtMS4wMS41NC0xLjQ3LjkxLS4xMi0uMjgtLjI1LS41Ni0uMzktLjgzLTIuMjItNC40MS02LjgtNy40Mi0xMi4wNC03LjQyLTEuMzUsMC0yLjY2LjItMy45LjU3LTEuNTUuNDYtMi45OCwxLjE4LTQuMjQsMi4xMy0yLjQ3LDEuODUtNC4yOCw0LjUxLTUuMDMsNy42LS4wOC4zMi0uMTUuNjUtLjIuOThIMHYzLjMxaDIuNDRjLjAzLjM1LjA3LjcuMTIsMS4wNCwxLjAzLDYuNDYsNi42MywxMS40LDEzLjM3LDExLjQsNy40MiwwLDEzLjQ4LTYuMDcsMTMuNDgtMTMuNTUsMC0uMTEsMC0uMjEsMC0uMzIsMC0uMjgtLjAyLS41Ni0uMDQtLjg0LjE5LS45Mi43Ni0xLjU0LDEuNDUtMS45NiwxLjQ2LS44OSwzLjQ1LS44NywzLjQ1LS44NywwLDAsMS45OS0uMDIsMy40NS44Ny42OS40MiwxLjI2LDEuMDQsMS40NSwxLjk2LS4wMi4yOC0uMDQuNTYtLjA0Ljg0LDAsLjExLDAsLjIxLDAsLjMyLDAsNy40OCw2LjA3LDEzLjU1LDEzLjQ4LDEzLjU1LDYuNzUsMCwxMi4zNS00Ljk0LDEzLjM3LTExLjQuMDUtLjM0LjA5LS42OS4xMi0xLjA0aDIuNDR2LTMuMzFoLS45Wk0xOC4zMyw0NS44Yy01LjMzLDAtOS43NSw0LjM1LTkuNzUsOS43NSwwLDEuOS41NSwzLjY4LDEuNTMsNS4xNS0xLjg0LTEuMzctMy4xNi0zLjM1LTMuNjgtNS42NC0uMDgtLjM0LS4xNC0uNjktLjE4LTEuMDQtLjA0LS4zNi0uMDYtLjczLS4wNi0xLjEsMC0uNzYuMS0xLjUuMjYtMi4yMS4wOC0uMzMuMTctLjY2LjI4LS45OCwxLjMyLTMuODIsNC45My02LjU2LDkuMi02LjU2LDMuNDMsMCw2LjUsMS44NCw4LjIxLDQuNi0xLjU5LTEuMjMtMy42Mi0xLjk2LTUuODItMS45NlpNNjIuMjcsNTQuMDFjLS4wNC4zNS0uMS43LS4xOCwxLjA0LS41MiwyLjI5LTEuODQsNC4yNy0zLjY4LDUuNjQuOTgtMS40NywxLjUzLTMuMjUsMS41My01LjE1LDAtNS4zOS00LjQxLTkuNzUtOS43NS05Ljc1LTIuMjEsMC00LjIzLjc0LTUuODIsMS45NiwxLjcyLTIuNzYsNC43OC00LjYsOC4yMS00LjYsNC4yOCwwLDcuODksMi43NCw5LjIsNi41Ni4xMS4zMi4yMS42NS4yOC45OC4xNi43MS4yNiwxLjQ1LjI2LDIuMjEsMCwuMzctLjAyLjc0LS4wNiwxLjFaIi8+CiAgICA8L2c+CiAgICA8Zz4KICAgICAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMTYuODQsMjcuOTRzLS4wMywwLS4wNCwwYy0uNTMtLjEtMS40Ni0xLjgxLTEuNjctMi4yMS0uMDUtLjA5LS4wOS0uMTctLjEzLS4yNi0uMDItLjAzLS4wMy0uMDctLjA1LS4xLS4zMy0uNzMtLjQ5LTEuNDYtLjY1LTIuMjctLjM2LTEuODYtLjYyLTMuNzQtLjgtNS42My0uMDUtLjY4LS4xLTEuMzYtLjEzLTIuMDQtLjAyLS42Ny0uMDEtMS4zMy0uMDItMiwuMDUtMS40NS4wNi0zLjYtLjY3LTMuNjMsMCwwLS4wMiwwLS4wMywwLS45My0uMDMtMi4wMiwxLjA5LTIuOTEsMi4zMywwLDAtLjAxLjAyLS4wMi4wMy0uNjMuODgtMS4xNSwxLjgxLTEuNDMsMi40My0xLjU5LDMuNDctMS4zOCw3LjUyLS4zMywxMS4xMi4zLDEuMDEuNjYsMi4wMSwxLjA5LDIuOTcuMy42OC42MiwxLjMzLjk4LDEuOTUsMCwwLC4xMS4xOS4xMS4xOS4wMi4wMy4wMy4wNi4wNS4wOSwwLC4wMS4wMS4wMy4wMi4wNC41Ny45OCwxLjUyLDIuODgsMi43NCwzLjUuMjUuMTQuNTMuMjIuODEuMjEuMDIsMCwuMDIsMCwuMDMsMCwuMjEsMCwuNDItLjA2LjYxLS4xNi4xMy0uMDcuMjUtLjE2LjM0LS4yOC4xLS4xNS4xNS0uMzQuMTQtLjUyLDAtLjE4LS4wNi0uMzYtLjEzLS41My0uMTctLjQ0LS4zLS45My0uNC0xLjQtLjI1LTEuMTYtLjE3LTIuNDUuODMtMy4yNS4xMS0uMDkuMjQtLjE3LjM3LS4yNC4zOS0uMjEuODMtLjMyLDEuMjctLjMxLDAsMCwwLDAsMCwwaDBaIi8+CiAgICAgIDxwYXRoIGNsYXNzPSJjbHMtMSIgZD0iTTU4LjMyLDEuMTVjLTIuNi0xLjU4LTUuOTMtMS43OS03Ljc1LDEuMDItMS42NSwyLjU0LTEuNDksNS42MS0xLjQyLDguNS4wOCwzLjI2LS4yMiw2LjUzLS45MSw5LjcyLDAsMC0uMDIuMS0uMDQuMTgtLjM2LS4wOS0uOTMtLjE3LTEuMi0uMjEtLjkxLS4xNC0xLjg2LS4wNy0yLjc5LjIxLS44LTIuNDQtMi41OC00LjE3LTQuOTktNC43OS0uNTMtLjE0LTEuMDctLjIyLTEuNjEtLjI0aC0uODFjLTIuMTIuMTQtNC4yLDEuMTItNS44MywyLjgyLTEuODQtMS40OS0zLjk4LTIuMDQtNi4xLTEuNTQtMS44OC40NS0zLjUxLDEuNzMtNC41OSwzLjU2LS42OS0zLjE5LS45OS02LjQ2LS45MS05LjcyLjA3LTIuODkuMjMtNS45Ni0xLjQyLTguNS0xLjgyLTIuODEtNS4xNS0yLjYtNy43NS0xLjAyQzEuMTksNi42My0uOTQsMTkuMjgsMi4xMywyOC42NmMuMDUuMTQuMDkuMjguMTQuNDIsMS4xNywzLjM4LDMuMTIsNi40OSw1LjA3LDkuNDZsLjAzLjA0Yy4yOC40NS41Ny44OS44NSwxLjM0Ljg1LS42LDEuNzgtMS4wOSwyLjc3LTEuNDgsMCwwLS4wMS0uMDItLjAyLS4wMy4wMSwwLC4wMy0uMDEuMDQtLjAyLDAtLjAxLS4wMi0uMDMtLjAzLS4wNC0uMTItLjE4LS4yNC0uMzYtLjM2LS41NS0uMDUtLjA3LS4wOS0uMTQtLjE0LS4yMi0uMDgtLjEyLS4xNi0uMjQtLjI0LS4zNy0uMDYtLjA5LS4xMi0uMTktLjE4LS4yOC0uMDYtLjEtLjEzLS4yLS4xOS0uMy0xLjcxLTIuNjctMy4zMi01LjQ3LTQuNDItOC40NmgwYy0uMDctLjItLjE0LS4zOS0uMi0uNTksMCwwLDAsMCwwLS4wMS0uODctMi41Ni0xLjM1LTUuMjQtMS4yNi04LjE2LjA1LTEuMTIuMTgtMi4yNS4zOS0zLjM3LjA0LS4yLjA5LS40MS4xNS0uNjIsMC0uMDMuMDEtLjA2LjAyLS4wOC4wNS0uMi4xMS0uNC4xNy0uNiwwLS4wMSwwLS4wMi4wMS0uMDQuMTMtLjQ0LjI4LS44OS40NC0xLjM0LjAxLS4wMy4wMi0uMDYuMDMtLjA5LjA3LS4yLjE1LS40LjIyLS41OS4wMS0uMDMuMDItLjA2LjA0LS4wOS4xOC0uNDUuMzctLjkxLjU3LTEuMzYuMDEtLjAzLjAzLS4wNS4wNC0uMDguMDktLjE5LjE4LS4zOS4yNy0uNTguMDItLjA0LjA0LS4wOC4wNi0uMTIuMS0uMi4yLS40LjMxLS42LDAtLjAxLjAxLS4wMy4wMi0uMDQuMTItLjIyLjI0LS40NC4zNi0uNjYsMC0uMDEuMDItLjAzLjAyLS4wNCwxLjE1LTIuMDEsMi41My0zLjc5LDQuNDgtNS4wOS40OS0uMzMsMS4wMi0uNjIsMS41OS0uNzcuNDgtLjEyLDEuMDUtLjE2LDEuNTIuMDMuNC4xNi42MS42Ljc4Ljk4LjM2LjgzLjQ1LDEuODEuNTUsMi43MS4xMS45Ny4xNSwxLjk2LjE3LDIuOTQuMDksNC4yNC4xNiw4LjQsMS40NywxMi40OS4wOC4yNi4xNy41My4yNy43OS4zOSwxLjA4LjgsMi4xOCwxLjQxLDMuMTYuMzIuNTEsMS4yOSwyLjAzLDIuMDMsMi4xOC4wNCwwLC4wOC4wMi4xMi4wMi4wNywwLC40Mi0yLjc3LjQ2LTMuMDMuMTQtLjkzLjI3LTEuODIuNjMtMi43LjU1LTEuMzMsMS41Ny0yLjU4LDMuMDMtMi45MiwxLjU5LS4zNywzLjI2LjQyLDQuNjEsMi4xN2wxLjEsMS40My45LTEuNTZjMS4zOS0yLjQxLDMuOTYtMy42OSw2LjIzLTMuMSwxLjkzLjUsMy4wNywyLjIyLDMuMTEsNC43MmwuMDQsMi41MywxLjk0LTEuNjNjLjkxLS43NiwyLjAzLTEuMTMsMi45OS0uOTguNjMuMSwxLjAyLjQzLDEuNDcuODMuMS4wOS42LjYzLjg0LDEuMDMuMjEuNC4yMy4zNS4zNiwxLjAxLDAsLjA1LDEuMDItMi4wOCwxLjQxLTMuMTYuMDktLjI2LjE4LS41Mi4yNy0uNzksMS4zMS00LjA4LDEuMzgtOC4yNCwxLjQ3LTEyLjQ5LjAyLS45OC4wNi0xLjk2LjE3LTIuOTQuMS0uODkuMTktMS44OC41NS0yLjcxLjE2LS4zOC4zOC0uODIuNzgtLjk4LjQ3LS4xOSwxLjA0LS4xNiwxLjUyLS4wMy41Ny4xNSwxLjEuNDQsMS41OS43NywxLjk1LDEuMjksMy4zNCwzLjA4LDQuNDgsNS4wOSwwLC4wMS4wMi4wMy4wMi4wNC4xMi4yMi4yNC40NC4zNi42NiwwLC4wMS4wMS4wMy4wMi4wNC4xMS4yLjIxLjQuMzEuNi4wMi4wNC4wNC4wOC4wNi4xMi4wOS4xOS4xOS4zOS4yNy41OC4wMS4wMy4wMy4wNS4wNC4wOC4yMS40NS40LjkuNTcsMS4zNi4wMS4wMy4wMi4wNi4wNC4wOS4wOC4yLjE1LjQuMjIuNTkuMDEuMDMuMDIuMDYuMDMuMDkuMTYuNDUuMzEuOS40NCwxLjM0LDAsLjAxLDAsLjAyLjAxLjA0LjA2LjIuMTEuNC4xNy42LDAsLjAzLjAxLjA2LjAyLjA4LjA1LjIxLjEuNDEuMTUuNjIuMjEsMS4xMi4zNCwyLjI1LjM5LDMuMzcuMDksMi45My0uMzgsNS42MS0xLjI2LDguMTYsMCwwLDAsMCwwLC4wMS0uMDcuMTktLjEzLjM5LS4yLjU4aDBjLTEuMSwzLTIuNzEsNS44LTQuNDIsOC40Ny0uMDYuMS0uMTMuMi0uMTkuMy0uMDYuMDktLjEyLjE5LS4xOC4yOC0uMDguMTItLjE2LjI0LS4yNC4zNy0uMDUuMDctLjA5LjE0LS4xNC4yMi0uMTIuMTgtLjI0LjM2LS4zNi41NSwwLC4wMS0uMDIuMDMtLjAzLjA0LjAxLDAsLjAzLjAxLjA0LjAyLDAsMC0uMDEuMDItLjAyLjAzLjk4LjM5LDEuOTEuODgsMi43NywxLjQ4LjI4LS40NS41Ny0uOS44NS0xLjM0bC4wMy0uMDRjMS45NS0yLjk3LDMuOS02LjA5LDUuMDctOS40Ni4wNS0uMTQuMS0uMjguMTQtLjQyLDMuMDctOS4zOC45NC0yMi4wMy04LjA3LTI3LjUxWiIvPgogICAgICA8cGF0aCBjbGFzcz0iY2xzLTEiIGQ9Ik02MC41NSwyNS42OWMxLjA1LTMuNiwxLjI2LTcuNjQtLjMzLTExLjEyLS42OS0xLjUtMi43Ny00Ljg0LTQuMzYtNC43OC0uMDEsMC0uMDIsMC0uMDMsMC0uOTkuMDQtLjYxLDQuMDItLjY0LDQuNzktLjA5LDEuOTYtLjI0LDMuOTItLjQ2LDUuODctLjEuODQtLjE4LDEuNjYtLjM1LDIuNDYtLjEzLjY0LS4zLDEuMjYtLjU2LDEuODktLjI1LjU5LTEuMzcsMy4xMy0yLjEzLDMuMTUuNTktLjAyLDEuMTguMTgsMS42NC41NSwxLC44LDEuMDgsMi4wOC44MywzLjI1LS4xLjQ2LS4yMi45Ni0uNCwxLjQtLjA3LjE3LS4xMi4zNS0uMTMuNTMsMCwuMTguMDMuMzcuMTQuNTIuMDguMTIuMjEuMjIuMzQuMjguMTkuMS40LjE1LjYxLjE2LDAsMCwuMDIsMCwuMDIsMCwxLjYyLjAzLDIuODctMi41MiwzLjU2LTMuNy45Ni0xLjY0LDEuNzItMy40MSwyLjI1LTUuMjRaIi8+CiAgICA8L2c+CiAgPC9nPgo8L3N2Zz4=" width="160" alt="Green Llama" style="display:block"></div>
<h1>GLerp Maintenance Window Admin</h1>
<p>Define a maintenance window to exclude the period from SLA calculations,
mark it on Grafana dashboards, and suppress alerts.</p>
{msg}
<div class="card">
<h2>Create Maintenance Window</h2>
<form method="POST" action="/window">
  <label>Site</label>
  <select name="site">
    <option value="__all__">All sites</option>
    {site_opts}
  </select>
  <div class="row">
    <div>
      <label>Start (local time)</label>
      <input type="datetime-local" name="start" required>
    </div>
    <div>
      <label>End (local time)</label>
      <input type="datetime-local" name="end" required>
    </div>
  </div>
  <div id="tzinfo" class="tz"></div>
  <label>Description</label>
  <input type="text" name="description"
         placeholder="e.g. ERPNext v16.1 upgrade" required>
  <input type="hidden" name="tz_offset" id="tz_offset" value="0">
  <p class="note">Times are read from your browser's local timezone and
  converted to UTC automatically.</p>
  <button type="submit" class="btn btn-blue">Create Maintenance Window</button>
</form>
</div>
<div class="card">
<h2>Maintenance Windows</h2>
{windows}
<p class="note">
  <strong>Active</strong> = window is ongoing now (alerts suppressed)&nbsp;·&nbsp;
  <strong>Upcoming</strong> = starts in the future&nbsp;·&nbsp;
  <strong>Past</strong> = completed.
  Times are shown in your browser's local timezone.
</p>
<p class="note">
  <strong>Note on SLA impact:</strong> the <em>maintenance-adjusted</em> uptime
  graphs only exclude a window's downtime <strong>after the window has ended</strong>.
  While a window is Active or Upcoming, the adjusted graph still matches the raw
  graph — it updates automatically once the end time passes (next time this page
  loads). The blue annotation lines/band appear immediately either way.
</p>
<p class="note">
  <strong>Note on alerts:</strong> while a window is Active, all matching GLerp
  alerts are <strong>silenced</strong> in Alertmanager — so <em>neither</em> firing
  (DOWN) <em>nor</em> resolved (UP) notifications are sent for those sites until the
  window ends. This is intentional. If you are testing alert delivery, make sure no
  maintenance window is currently active.
</p>
</div>
</body>
</html>
"""

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _http(method, url, body=None, headers=None):
    data = body.encode() if isinstance(body, str) else body
    req  = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return 0, str(e)


def grafana(method, path, body=None):
    hdrs = {"Authorization": f"Bearer {GRAFANA_TOKEN}"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
        body = json.dumps(body)
    return _http(method, GRAFANA_URL.rstrip("/") + path, body, hdrs)


def alertmanager(method, path, body=None):
    hdrs = {}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
        body = json.dumps(body)
    return _http(method, AM_URL.rstrip("/") + path, body, hdrs)


def vm_post_text(path, body):
    return _http("POST", VM_URL.rstrip("/") + path, body,
                 {"Content-Type": "text/plain"})

# ── Domain helpers ────────────────────────────────────────────────────────────

def get_sites():
    qs  = urllib.parse.urlencode({"match[]": 'probe_success{job="glerp-sites-login"}'})
    st, body = _http("GET", VM_URL.rstrip("/") + f"/api/v1/label/site/values?{qs}")
    if st == 200:
        return sorted(json.loads(body).get("data", []))
    return []


def write_metric(site, start_ms, end_ms):
    lines = []
    ts = start_ms
    while ts <= end_ms:
        lines.append(f'{METRIC_WINDOW}{{site="{site}"}} 1 {ts}')
        ts += 60_000
    result = vm_post_text("/api/v1/import/prometheus", "\n".join(lines) + "\n")
    # Excused-failure samples (what the maintenance-adjusted SLA formula actually
    # subtracts) require the real probe_success==0 samples to already exist in VM,
    # so they can only be written for the portion of the window that is in the PAST.
    # For a window created entirely in the past, this fills it immediately.
    # For an active/future window, the past portion (if any) is filled now and the
    # still-pending portion is filled later by the reconcile sweep (see
    # reconcile_recent_windows()), which re-checks recently-ended windows on each
    # admin-tool request. Until a window fully ends, its adjusted SLA is not yet
    # final — documented in the dashboard ⓘ panels and the admin UI.
    if end_ms < int(time.time() * 1000):
        _delete_excused_failures(site, start_ms, end_ms)
        _write_excused_failures(site, start_ms, end_ms)
    return result


def _delete_excused_failures(site, start_ms, end_ms):
    """Delete any existing excused_failures samples for the given window before re-writing."""
    if site == "all":
        sel = METRIC_EXCUSED
    else:
        sel = f'{METRIC_EXCUSED}{{site="{site}"}}'
    qs = urllib.parse.urlencode({
        "match[]": sel,
        "start": int(start_ms / 1000),
        "end":   int(end_ms   / 1000),
    })
    _http("POST", VM_URL.rstrip("/") + f"/api/v1/admin/tsdb/delete_series?{qs}")


def _write_excused_failures(site, start_ms, end_ms):
    """Query probe_success during the window; write a failure sample for each 0.

    For site="all" we must NOT filter on site="all" (no series carries that
    label). Instead query every site, then write each excused sample under the
    result's OWN site label so the dashboard's
    glerp_maintenance_excused_failures{site=~"$site"} matches real per-site data.
    """
    if site == "all":
        selector = 'probe_success{job="glerp-sites-login"}'
    else:
        selector = f'probe_success{{job="glerp-sites-login",site="{site}"}}'
    qs = urllib.parse.urlencode({
        "query": selector,
        "start": int(start_ms / 1000),
        "end":   int(end_ms   / 1000),
        "step":  "30s",
    })
    st, body = _http("GET", VM_URL.rstrip("/") + f"/api/v1/query_range?{qs}")
    if st != 200:
        return
    lines = []
    for result in json.loads(body).get("data", {}).get("result", []):
        # Use the series' own site label (handles the "all" fan-out correctly).
        result_site = result.get("metric", {}).get("site", site)
        for ts_str, val_str in result.get("values", []):
            if float(val_str) == 0:
                ts_ms = int(float(ts_str) * 1000)
                lines.append(
                    f'{METRIC_EXCUSED}{{site="{result_site}"}} 1 {ts_ms}')
    if lines:
        vm_post_text("/api/v1/import/prometheus", "\n".join(lines) + "\n")


def delete_metric(site, start_ms, end_ms):
    """Remove glerp_maintenance_window and glerp_maintenance_excused_failures samples."""
    if site == "all":
        window_sel  = METRIC_WINDOW
        excused_sel = METRIC_EXCUSED
    else:
        window_sel  = f'{METRIC_WINDOW}{{site="{site}"}}'
        excused_sel = f'{METRIC_EXCUSED}{{site="{site}"}}'
    start_s = int(start_ms / 1000)
    end_s   = int(end_ms   / 1000)
    for sel in (window_sel, excused_sel):
        qs = urllib.parse.urlencode({"match[]": sel, "start": start_s, "end": end_s})
        _http("POST", VM_URL.rstrip("/") + f"/api/v1/admin/tsdb/delete_series?{qs}")
    return 204, ""


def create_annotation(site, start_ms, end_ms, description, silence_id=""):
    tags = ["maintenance", ("all" if site == "__all__" else site)]
    if silence_id:
        tags.append(f"silence:{silence_id}")
    return grafana("POST", "/api/annotations", {
        "text":    description,
        "tags":    tags,
        "time":    start_ms,
        "timeEnd": end_ms,
    })


def get_annotation(ann_id):
    st, body = grafana("GET", f"/api/annotations/{ann_id}")
    if st == 200:
        return json.loads(body)
    return None


def mark_annotation_deleted(ann_id, original_ann, delete_comment):
    """Delete the Grafana annotation so the blue band is removed from dashboards."""
    return grafana("DELETE", f"/api/annotations/{ann_id}")


def create_silence(site, start_iso, end_iso, description):
    if site == "__all__":
        matchers = [{"name": "alertname", "value": "GLerp.*",
                     "isRegex": True,  "isEqual": True}]
    else:
        matchers = [{"name": "site", "value": site,
                     "isRegex": False, "isEqual": True}]
    st, body = alertmanager("POST", "/api/v2/silences", {
        "matchers":  matchers,
        "startsAt":  start_iso,
        "endsAt":    end_iso,
        "createdBy": "glerp-maintenance-admin",
        "comment":   description,
    })
    silence_id = ""
    if st in (200, 201):
        try:
            silence_id = json.loads(body).get("silenceID", "")
        except Exception:
            pass
        return st, "", silence_id
    return st, body[:300], ""


def expire_silence(silence_id):
    """Expire an AlertManager silence immediately."""
    return alertmanager("DELETE", f"/api/v2/silences/{silence_id}")


def parse_local_dt(s, tz_offset_minutes=0):
    """
    Parse a naive datetime-local browser string and return UTC epoch ms.
    tz_offset_minutes = browser's getTimezoneOffset():
      positive for UTC-N zones (e.g. CDT/UTC-5 → +300)
      negative for UTC+N zones (e.g. UTC+2 → -120)
    UTC = local + tz_offset_minutes.
    """
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(f"Cannot parse '{s}' as a date/time")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc) + timedelta(minutes=tz_offset_minutes)
    return int(dt.timestamp() * 1000)

# ── Window listing ────────────────────────────────────────────────────────────

def _ann_site(ann):
    for t in ann.get("tags", []):
        if t != "maintenance" and not t.startswith("silence:"):
            return t
    return "?"


def _ann_silence_id(ann):
    for t in ann.get("tags", []):
        if t.startswith("silence:"):
            return t[len("silence:"):]
    return None


def _fmt_ms(ms):
    if not ms:
        return "—"
    utc_str = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f'<span class="local-time" data-ms="{ms}">{utc_str}</span>'


def get_all_windows():
    st, body = grafana("GET", "/api/annotations?tags=maintenance&limit=200")
    if st == 200:
        return sorted(json.loads(body), key=lambda x: x.get("time", 0), reverse=True)
    return []


def _excused_exists(site, start_ms, end_ms):
    """True if any excused_failures sample already exists in [start,end] for site."""
    sel = (METRIC_EXCUSED if site == "all"
           else f'{METRIC_EXCUSED}{{site="{site}"}}')
    qs = urllib.parse.urlencode({
        "query": sel,
        "start": int(start_ms / 1000),
        "end":   int(end_ms   / 1000),
        "step":  "300s",
    })
    st, body = _http("GET", VM_URL.rstrip("/") + f"/api/v1/query_range?{qs}")
    if st != 200:
        return False  # on error, allow the write attempt
    for r in json.loads(body).get("data", {}).get("result", []):
        if r.get("values"):
            return True
    return False


def reconcile_recent_windows():
    """Backfill excused_failures for windows that have ENDED but were created while
    active/future (so write_metric's create-time branch skipped them).

    This runs opportunistically on admin-tool requests — NOT on a timer/CronJob —
    so there is no continuous CPU cost. It only does work when a window has ended
    and its excused samples are missing; otherwise each annotation costs one cheap
    existence query. Keeps the "write-on-conclude" model correct without polling.
    """
    now_ms = int(time.time() * 1000)
    try:
        anns = get_all_windows()
    except Exception:
        return
    for ann in anns:
        start = ann.get("time", 0)
        end   = ann.get("timeEnd", start)
        if not end or end >= now_ms:
            continue  # still active/upcoming — nothing final to write yet
        site = _ann_site(ann)
        if not site:
            continue
        if _excused_exists(site, start, end):
            continue  # already filled (e.g. window was created in the past)
        _delete_excused_failures(site, start, end)
        _write_excused_failures(site, start, end)


def refill_overlapping_windows(deleted_site, del_start_ms, del_end_ms, skip_ann_id=None):
    """After a window is deleted, re-derive excused_failures for any OTHER ended
    window that overlaps the deleted range.

    Deleting window A removes excused_failures across A's whole [start,end]. If a
    different window B overlapped A, B's excused samples in the overlap are now gone,
    silently corrupting B's adjusted SLA. Since excused_failures is always re-derived
    from the untouched probe_success data, we can safely rewrite each overlapping
    window's full range to restore it. "all" overlaps every site's windows.
    """
    now_ms = int(time.time() * 1000)
    try:
        anns = get_all_windows()
    except Exception:
        return
    for ann in anns:
        if skip_ann_id is not None and ann.get("id") == skip_ann_id:
            continue  # the window being deleted — don't resurrect it
        b_start = ann.get("time", 0)
        b_end   = ann.get("timeEnd", b_start)
        if not b_end or b_end >= now_ms:
            continue  # only ended windows have authoritative excused data
        # overlap test
        if b_end <= del_start_ms or b_start >= del_end_ms:
            continue
        b_site = _ann_site(ann)
        if not b_site:
            continue
        # "all" on either side means the ranges share sites
        if deleted_site != "all" and b_site != "all" and b_site != deleted_site:
            continue
        _delete_excused_failures(b_site, b_start, b_end)
        _write_excused_failures(b_site, b_start, b_end)


def render_windows():
    try:
        anns = get_all_windows()
    except Exception as e:
        return f"<p class='err'>Could not load windows: {e}</p>"

    if not anns:
        return "<p><em>No maintenance windows recorded yet.</em></p>"

    now_ms = int(time.time() * 1000)
    rows   = []
    for ann in anns:
        site   = _ann_site(ann)
        start  = ann.get("time",    0)
        end    = ann.get("timeEnd", start)
        text   = ann.get("text",    "")
        ann_id = ann["id"]

        if start > now_ms:
            css, label = "s-upcoming", "Upcoming"
        elif end > now_ms:
            css, label = "s-active",   "Active"
        else:
            css, label = "s-past",     "Past"

        display = html.escape((text[:72] + "…") if len(text) > 72 else text)

        action = (
            f'<button class="btn btn-red" onclick="showDel({ann_id})">Delete…</button>'
            f'<div class="del-panel" id="del-{ann_id}">'
            f'<form method="POST" action="/delete">'
            f'<input type="hidden" name="annotation_id" value="{ann_id}">'
            f'<label style="font-size:.8rem;margin-top:0">Deletion reason (required)</label>'
            f'<input type="text" name="delete_comment"'
            f'       placeholder="e.g. Window cancelled — upgrade postponed" required>'
            f'<div style="margin-top:8px">'
            f'<button type="submit" class="btn btn-red">Confirm Delete</button>'
            f'&nbsp;<button type="button" class="btn btn-grey"'
            f'        onclick="hideDel({ann_id})">Cancel</button>'
            f'</div></form></div>'
        )

        rows.append(
            f"<tr>"
            f"<td>{html.escape(site)}</td>"
            f"<td>{_fmt_ms(start)}</td>"
            f"<td>{_fmt_ms(end)}</td>"
            f"<td>{display}</td>"
            f'<td class="{css}">{label}</td>'
            f"<td>{action}</td>"
            f"</tr>"
        )

    return (
        "<table>"
        "<tr><th>Site</th><th>Start</th><th>End</th>"
        "<th>Description</th><th>Status</th><th>Action</th></tr>"
        + "".join(rows)
        + "</table>"
    )

# ── Message builder ───────────────────────────────────────────────────────────

def _build_msg(errors, ok_html, info_lines=None):
    """Return an HTML message div. Errors → red; no errors → ok_html; info_lines → blue info div."""
    info_html = ('<div class="msg info">' + "<br>".join(info_lines) + "</div>") if info_lines else ""
    if errors:
        return '<div class="msg err">' + "<br>".join(errors) + "</div>" + info_html
    return ok_html + info_html

# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def _auth_ok(self):
        hdr = self.headers.get("Authorization", "")
        if not hdr.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(hdr[6:]).decode()
            u, p = raw.split(":", 1)
            return u == ADMIN_USER and p == ADMIN_PASS
        except Exception:
            return False

    def _challenge(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="GLerp Maintenance Admin"')
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h1>401 Authentication required</h1>")

    def _send_html(self, html, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _render(self, msg=""):
        # Opportunistically finalize any window that has ended since last view.
        # No timer/CronJob — runs only when the admin tool is actually loaded.
        try:
            reconcile_recent_windows()
        except Exception:
            pass  # never let backfill break page rendering
        sites     = get_sites()
        site_opts = "\n    ".join(
            f'<option value="{s}">{s}</option>' for s in sites
        )
        return PAGE.format(msg=msg, site_opts=site_opts, windows=render_windows())

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if not self._auth_ok():
            self._challenge()
            return
        self._send_html(self._render())

    def do_POST(self):
        if not self._auth_ok():
            self._challenge()
            return

        length = int(self.headers.get("Content-Length", 0))
        raw    = self.rfile.read(length).decode()
        params = urllib.parse.parse_qs(raw)

        def p(k):
            return params.get(k, [""])[0].strip()

        # ── CREATE ──────────────────────────────────────────────────────────
        if self.path == "/window":
            site        = p("site")
            start_str   = p("start")
            end_str     = p("end")
            description = p("description")
            try:
                tz_offset = int(p("tz_offset") or "0")
            except ValueError:
                tz_offset = 0

            if not all([site, start_str, end_str, description]):
                self._send_html(self._render(
                    '<div class="msg err">All fields are required.</div>'))
                return

            try:
                start_ms = parse_local_dt(start_str, tz_offset)
                end_ms   = parse_local_dt(end_str,   tz_offset)
            except ValueError as e:
                self._send_html(self._render(
                    f'<div class="msg err">Invalid date/time: {e}</div>'))
                return

            if end_ms <= start_ms:
                self._send_html(self._render(
                    '<div class="msg err">End time must be after start time.</div>'))
                return

            start_iso = datetime.fromtimestamp(
                start_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            end_iso   = datetime.fromtimestamp(
                end_ms   / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            known_sites = get_sites()
            if site != "__all__" and site not in known_sites:
                self._send_html(self._render(
                    f'<div class="msg err">Unknown site: {html.escape(site)}</div>'))
                return
            sites_to_write = known_sites if site == "__all__" else [site]
            errors  = []
            notices = []

            # 1. Write VictoriaMetrics metric
            for s in sites_to_write:
                st, _ = write_metric(s, start_ms, end_ms)
                if st not in (200, 204):
                    errors.append(f"VictoriaMetrics write failed for '{s}' (HTTP {st})")

            # 2. Create AlertManager silence (do this before annotation so we
            #    can store the silence ID in the annotation tags)
            st, am_err, silence_id = create_silence(site, start_iso, end_iso, description)
            if st not in (200, 201):
                if st == 400 and "past" in am_err.lower():
                    notices.append(
                        "AlertManager silence was not created because the window end time "
                        "is in the past — this is expected for retroactive entries. "
                        "No silence is needed since the period has already ended."
                    )
                else:
                    errors.append(f"AlertManager silence failed (HTTP {st}): {am_err}")

            # 3. Create Grafana annotation (carries silence ID in tags)
            st, _ = create_annotation(site, start_ms, end_ms, description, silence_id)
            if st not in (200, 204):
                errors.append(f"Grafana annotation failed (HTTP {st}) — check GRAFANA_TOKEN")

            label = "all sites" if site == "__all__" else f"<strong>{html.escape(site)}</strong>"
            silence_note = f" · AlertManager silence created (ID: {silence_id})" if silence_id else ""
            ok_html = (
                f'<div class="msg ok">Maintenance window created for {label}:<br>'
                f"UTC {start_iso} → {end_iso}<br>"
                f"VictoriaMetrics metric written · Grafana annotation created"
                f"{silence_note}</div>"
            )
            msg = _build_msg(errors, ok_html, notices or None)

            self._send_html(self._render(msg))
            return

        # ── DELETE ──────────────────────────────────────────────────────────
        if self.path == "/delete":
            ann_id_str     = p("annotation_id")
            delete_comment = p("delete_comment")

            if not ann_id_str or not delete_comment:
                self._send_html(self._render(
                    '<div class="msg err">Annotation ID and deletion reason are required.</div>'))
                return

            try:
                ann_id = int(ann_id_str)
            except ValueError:
                self._send_html(self._render(
                    '<div class="msg err">Invalid annotation ID.</div>'))
                return

            ann = get_annotation(ann_id)
            if not ann:
                self._send_html(self._render(
                    '<div class="msg err">Maintenance window not found in Grafana.</div>'))
                return

            site       = _ann_site(ann)
            silence_id = _ann_silence_id(ann)
            start_ms   = ann.get("time",    0)
            end_ms     = ann.get("timeEnd", start_ms)

            notices = []
            errors  = []

            # 1. Expire AlertManager silence
            if silence_id:
                st, _ = expire_silence(silence_id)
                if st in (200, 204):
                    notices.append("AlertManager silence expired")
                else:
                    notices.append(
                        "Note: AlertManager silence may have already expired "
                        f"(HTTP {st}) — check Alerting → Silences if needed")
            else:
                notices.append(
                    "Note: no silence ID recorded on this window — "
                    "expire any active silence manually via Alerting → Silences")

            # 2. Remove VictoriaMetrics metric samples for the window
            st, _ = delete_metric(site, start_ms, end_ms)
            if st in (200, 204):
                notices.append("VictoriaMetrics metric samples deleted")
            else:
                notices.append(
                    f"Note: VictoriaMetrics delete returned HTTP {st} — "
                    "samples may persist until background merge completes")

            # 2b. Re-derive excused_failures for any OTHER ended window that
            # overlapped this one — deleting this window's range also wiped their
            # excused samples in the overlap. Safe: re-derived from probe_success.
            try:
                refill_overlapping_windows(site, start_ms, end_ms, skip_ann_id=ann_id)
            except Exception:
                pass

            # 3. Delete Grafana annotation (removes blue band from dashboards immediately)
            st, body = mark_annotation_deleted(ann_id, ann, delete_comment)
            if st in (200, 204):
                notices.append("Grafana annotation deleted (blue band removed from dashboards)")
            else:
                errors.append(f"Could not delete Grafana annotation (HTTP {st}): {body[:120]}")

            ok_html = (
                '<div class="msg ok">Window deleted successfully:<br>'
                + " · ".join(notices) + "</div>"
            )
            msg = _build_msg(errors, ok_html, notices if errors else None)

            self._send_html(self._render(msg))
            return

        self.send_response(404)
        self.end_headers()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"GLerp maintenance admin listening on :{port}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
