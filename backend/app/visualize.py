"""Render validated charts/function graphs; generated source is never executed."""
import html
import math


def finalize_visual(data):
    visual = data.get("visualization")
    if visual is None and "chart" in data:
        visual = {"type":"chart","content":data["chart"]}
    if not isinstance(visual, dict):
        raise ValueError("Visualize requires a structured artifact")
    kind = visual.get("type")
    if not isinstance(kind, str):
        raise ValueError("Visualization type must be a string")
    content = visual.get("content")
    if kind == "function_graph":
        return render_function_graph(content)
    if kind != "chart":
        if kind not in {"svg", "html", "mermaid", "manim"} or not isinstance(content,str) or not content.strip() or len(content)>50000:
            raise ValueError("Invalid visualization source")
        return {"type":kind, "content":content, "rendered":False, "executable":False, "status":"unsupported", "reason":"Export source only; active rendering unavailable"}
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


# A declarative vocabulary, not an expression language. No code parser or evaluator.
_FUNCTION_PARAMS = {
    "linear": {"m": 1, "b": 0},
    "quadratic": {"a": 1, "b": 0, "c": 0},
    "sine": {"amplitude": 1, "frequency": 1, "phase": 0, "offset": 0},
    "cosine": {"amplitude": 1, "frequency": 1, "phase": 0, "offset": 0},
}
_COLORS = ("#315cf6", "#c13570", "#14804a", "#995a00", "#7543bd", "#007f94", "#ae332b", "#545c6b")


def _number(value, limit, name):
    # Check bounds before isfinite: Python accepts arbitrarily large integers.
    if type(value) not in (int, float) or abs(value) > limit or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number within ±{limit:g}")
    return float(value)


def _keys(obj, allowed, name):
    if not isinstance(obj, dict) or set(obj) - set(allowed):
        raise ValueError(f"Invalid {name} fields")


def _function_value(kind, p, x):
    if kind == "linear":
        return p["m"] * x + p["b"]
    if kind == "quadratic":
        return (p["a"] * x + p["b"]) * x + p["c"]
    angle = p["frequency"] * x + p["phase"]
    wave = math.sin(angle) if kind == "sine" else math.cos(angle)
    return p["amplitude"] * wave + p["offset"]


def render_function_graph(content):
    """Compute bounded curves on a shared domain and serialize trusted SVG.

    content: {domain:[xmin,xmax], samples:101, curves:[
      {function:"quadratic", parameters:{a:1,b:0,c:0}, label:"y=x²"}]}
    Linear uses m,b; sine/cosine use amplitude,frequency,phase,offset (radians).
    Each optional numeric parameter has the default in _FUNCTION_PARAMS.
    Returned points are deterministic samples, not a symbolic solution or proof.
    """
    _keys(content, {"domain", "samples", "curves"}, "function graph")
    domain = content.get("domain", [-5, 5])
    if not isinstance(domain, list) or len(domain) != 2:
        raise ValueError("Function domain must be [minimum, maximum]")
    xmin, xmax = [_number(v, 1e4, "Domain endpoint") for v in domain]
    if xmax - xmin < 1e-6:
        raise ValueError("Function domain must increase by at least 0.000001")
    samples = content.get("samples", 101)
    if type(samples) is not int or not 2 <= samples <= 501:
        raise ValueError("Function samples must be an integer from 2 to 501")
    curves = content.get("curves")
    if not isinstance(curves, list) or not 1 <= len(curves) <= 8:
        raise ValueError("Function graph requires 1–8 curves")
    computed = []
    for curve in curves:
        _keys(curve, {"function", "parameters", "label"}, "curve")
        kind = curve.get("function")
        if not isinstance(kind, str) or kind not in _FUNCTION_PARAMS:
            raise ValueError("Unsupported function; choose linear, quadratic, sine or cosine")
        params = curve.get("parameters", {})
        _keys(params, _FUNCTION_PARAMS[kind], "function parameters")
        params = {k: _number(params.get(k, v), 1e6, "Parameter") for k, v in _FUNCTION_PARAMS[kind].items()}
        label = curve.get("label", kind)
        if not isinstance(label, str) or len(label) > 80 or any(ord(c) < 32 for c in label):
            raise ValueError("Function label must be text of at most 80 printable characters")
        points = []
        for i in range(samples):
            x = xmax if i == samples - 1 else xmin + (xmax - xmin) * i / (samples - 1)
            y = _number(_function_value(kind, params, x), 1e15, "Computed value")
            points.append([x, y])
        computed.append({"function": kind, "parameters": params, "label": label, "points": points})

    ymin = min(point[1] for curve in computed for point in curve["points"])
    ymax = max(point[1] for curve in computed for point in curve["points"])
    padding = (ymax - ymin) * .06 or max(1, abs(ymin) * .06)
    ymin -= padding
    ymax += padding
    px = lambda x: 65 + (x - xmin) / (xmax - xmin) * 590
    py = lambda y: 325 - (y - ymin) / (ymax - ymin) * 290
    height = 400 + 22 * len(computed)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 {height}" role="img">',
             '<title>Sampled function graph</title>',
             '<desc>Server-computed numeric samples. Curves are joined by straight segments.</desc>',
             f'<rect width="700" height="{height}" fill="#fff"/>']
    for i in range(6):
        x, y = xmin + (xmax-xmin)*i/5, ymin + (ymax-ymin)*i/5
        parts.extend([
            f'<line x1="{px(x):.2f}" x2="{px(x):.2f}" y1="35" y2="325" stroke="#e1e6ee"/>',
            f'<line x1="65" x2="655" y1="{py(y):.2f}" y2="{py(y):.2f}" stroke="#e1e6ee"/>',
            f'<text x="{px(x):.2f}" y="348" text-anchor="middle" font-size="11" fill="#15213a">{x:.4g}</text>',
            f'<text x="60" y="{py(y)+4:.2f}" text-anchor="end" font-size="11" fill="#15213a">{y:.4g}</text>'])
    if xmin <= 0 <= xmax:
        parts.append(f'<line x1="{px(0):.2f}" x2="{px(0):.2f}" y1="35" y2="325" stroke="#526079"/>')
    if ymin <= 0 <= ymax:
        parts.append(f'<line x1="65" x2="655" y1="{py(0):.2f}" y2="{py(0):.2f}" stroke="#526079"/>')
    for i, curve in enumerate(computed):
        coords = " ".join(f"{px(x):.2f},{py(y):.2f}" for x,y in curve["points"])
        parts.append(f'<polyline fill="none" stroke="{_COLORS[i]}" stroke-width="2" points="{coords}"/>')
        parts.append(f'<text x="65" y="{390+i*22}" font-size="12" fill="{_COLORS[i]}">{html.escape(curve["label"])}</text>')
    parts.extend(['<text x="650" y="370" font-size="12" fill="#15213a">x</text>',
                  '<text x="24" y="24" font-size="12" fill="#15213a">y</text>', '</svg>'])
    return {"type": "function_graph", "content": {"domain": [xmin, xmax], "samples": samples,
            "curves": [{k:v for k,v in curve.items() if k != "points"} for curve in computed]},
            "rendered": True, "executable": False, "svg": "".join(parts),
            "computed": {"y_range": [ymin, ymax], "curves": computed},
            "limitations": ["Finite sampled curves, not symbolic analysis; features between samples may be missed."]}
