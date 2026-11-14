"""Render only validated chart data; other formats are inert source exports."""
import html
import math


def finalize_visual(data):
    visual = data.get("visualization")
    if visual is None and "chart" in data:
        visual = {"type":"chart","content":data["chart"]}
    if not isinstance(visual, dict):
        raise ValueError("Visualize requires a structured artifact")
    kind = visual.get("type")
    content = visual.get("content")
    if kind != "chart":
        if kind not in {"svg", "html", "mermaid", "manim"} or not isinstance(content,str) or not content.strip() or len(content)>50000:
            raise ValueError("Invalid visualization source")
        return {"type":kind, "content":content, "rendered":False, "reason":"Export source only; active rendering unavailable"}
    if not isinstance(content, dict) or content.get("type","bar") not in {"bar","line"}:
        raise ValueError("Chart must use bar or line data")
    labels, values = content.get("labels"), content.get("values")
    if not isinstance(labels,list) or not isinstance(values,list) or not 1<=len(labels)==len(values)<=20:
        raise ValueError("Chart needs 1–20 labels and matching values")
    if any(not isinstance(x,str) or len(x)>50 for x in labels) or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>1e9 for x in values):
        raise ValueError("Invalid chart labels or values")
    lo,hi=min(0,min(values)),max(0,max(values))
    span=hi-lo or 1
    y=lambda v: round(32 + (hi-v)/span*275,2)
    base=y(0); w=600/len(values)
    parts=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 360" role="img">','<rect width="680" height="360" fill="#fff"/>',f'<line x1="38" x2="640" y1="{base}" y2="{base}" stroke="#526079"/>']
    coords=[]
    for i,(label,value) in enumerate(zip(labels,values)):
        x=40+w*(i+.5)
        coords.append(f"{x:.2f},{y(value)}")
        if content.get("type","bar")=="bar":
            parts.append(f'<rect x="{x-w*.29:.2f}" y="{min(base,y(value))}" width="{w*.58:.2f}" height="{abs(base-y(value)):.2f}" fill="#315cf6"/>')
        parts.append(f'<text x="{x:.2f}" y="335" text-anchor="middle" font-size="11" fill="#15213a">{html.escape(label[:max(3,int(w/7))])}</text>')
    if content.get("type")=="line":
        parts.append('<polyline fill="none" stroke="#315cf6" stroke-width="3" points="'+' '.join(coords)+'"/>')
    parts.append('</svg>')
    return {"type":"chart","content":content,"rendered":True,"svg":"".join(parts)}
