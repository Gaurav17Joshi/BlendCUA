"""Reference-space path data for the Step 2 iron-gate ornament.

The image is the construction datum: paths live in native 1024 px reference
coordinates and are projected through GateRef only inside Blender.  The
centreline anchors follow the traced upper/lower graph overlays saved beside
this run; Catmull-Rom resampling only smooths the measured graph between those
anchors.  The two mirrored halves retain shared centreline node ids.
"""
from __future__ import annotations
import math

AXIS_PX = 512.0
DISPLAY_SIZE = 6.744237
STRAP_WIDTH = 13.0 / 1024.0 * DISPLAY_SIZE
STRAP_DEPTH = 0.030
REF_NAME = "GateRef"
DEPTH_OFFSET = -0.12  # local image-normal -Z maps to world +Y, in front of GateRef


def catmull(points, samples=5):
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) < 2:
        return pts
    ext = [pts[0]] + pts + [pts[-1]]
    out = []
    for i in range(len(pts) - 1):
        p0, p1, p2, p3 = ext[i:i + 4]
        for j in range(samples + (1 if i == len(pts) - 2 else 0)):
            t = j / float(samples)
            t2, t3 = t*t, t*t*t
            x = 0.5 * (2*p1[0] + (-p0[0] + p2[0])*t
                       + (2*p0[0] - 5*p1[0] + 4*p2[0] - p3[0])*t2
                       + (-p0[0] + 3*p1[0] - 3*p2[0] + p3[0])*t3)
            y = 0.5 * (2*p1[1] + (-p0[1] + p2[1])*t
                       + (2*p0[1] - 5*p1[1] + 4*p2[1] - p3[1])*t2
                       + (-p0[1] + 3*p1[1] - 3*p2[1] + p3[1])*t3)
            out.append((x, y))
    return out


def path(name, anchors, start=None, end=None, samples=5, anchor_nodes=None):
    points = catmull(anchors, samples)
    rec = {"name": name, "points_px": [[round(x, 3), round(y, 3)]
                                          for x, y in points]}
    node_ids = [None] * len(points)
    if start is not None:
        node_ids[0] = start
        rec["start_node"] = start
    if end is not None:
        node_ids[-1] = end
        rec["end_node"] = end
    for anchor_index, node in (anchor_nodes or {}).items():
        sample_index = min(int(anchor_index) * int(samples), len(points) - 1)
        node_ids[sample_index] = node
    if any(node is not None for node in node_ids):
        rec["node_ids"] = node_ids
    return rec


def _upper_left():
    return [
        path("heart_outer_L", [(512,200),(495,170),(470,150),(440,140),(410,142),(385,160),(370,190),(368,225),(380,260),(405,290),(435,315),(465,340),(490,365),(500,395),(512,434)], "C_UP", "C_LOW", anchor_nodes={13: "HEART_LOWER_BRANCH_L"}),
        path("heart_inner_L", [(510,200),(490,193),(472,179),(450,171),(430,177),(418,193),(420,215),(436,230),(455,231),(470,220),(472,205),(462,196)], "C_UP", "HEART_INNER_TIP_L"),
        path("heart_lower_curl_L", [(500,395),(492,375),(480,350),(467,335),(452,332),(440,319),(442,304),(454,294),(468,298),(478,310),(476,324),(466,333)], "HEART_LOWER_BRANCH_L", "HEART_LOWER_TIP_L"),
        path("lower_big_lobe_L", [(512,434),(500,447),(485,470),(460,490),(430,500),(400,495),(378,478),(369,452),(374,425),(390,405),(412,398),(434,405),(447,423),(447,444),(435,459),(417,463),(403,454)], "C_LOW", "LOW_BIG_TIP_L", anchor_nodes={10: "LOW_MID_L"}),
        path("lower_mid_lobe_L", [(412,398),(390,385),(365,360),(340,340),(315,337),(292,350),(280,375),(285,400),(305,418),(330,420),(350,408),(358,388),(350,372),(335,365)], "LOW_MID_L", "LOW_MID_TIP_L", anchor_nodes={10: "LOW_MID_BRANCH_L"}),
        path("lower_small_curl_L", [(350,408),(370,420),(390,430),(404,445),(420,450),(430,440),(428,425),(416,418),(405,423),(404,435)], "LOW_MID_BRANCH_L", "LOW_SMALL_TIP_L"),
        path("top_lobe_L", [(300,210),(280,180),(260,150),(258,120),(272,92),(300,76),(330,78),(355,95),(370,120),(370,145),(360,165),(344,175),(326,170),(316,157),(317,143),(328,135)], "TOP_LOBE_L", "TOP_LOBE_TIP_L", anchor_nodes={10: "TOP_LEAF_BASE_L"}),
        path("top_leaf_L", [(360,165),(377,145),(390,125),(400,105)], "TOP_LEAF_BASE_L", "TOP_LEAF_TIP_L"),
        path("diag_inner_L", [(300,210),(325,245),(355,280),(390,315),(425,350),(465,385),(500,420)], "TOP_LOBE_L", "DIAG_LOW_L"),
        path("side_lobe_L", [(274,205),(245,190),(210,182),(178,190),(155,215),(148,250),(155,285),(180,312),(210,322),(238,310),(250,288),(245,263),(225,245),(202,248),(188,262),(188,278)], "TOP_SIDE_L", "SIDE_LOBE_TIP_L", anchor_nodes={8: "SIDE_CURL_NODE_L"}),
        path("side_small_curl_L", [(210,322),(230,340),(232,360),(220,377),(203,380),(190,369),(190,352),(202,344),(215,350),(218,362),(210,370)], "SIDE_CURL_NODE_L", "SIDE_SMALL_TIP_L"),
        path("side_outer_L", [(274,205),(292,238),(300,275),(300,315),(288,350),(270,382),(245,410),(230,445),(225,480)], "TOP_SIDE_L", "LOW_SIDE_L"),
        path("side_to_mid_L", [(225,480),(260,450),(290,420),(330,400),(370,410),(412,398)], "LOW_SIDE_L", "LOW_MID_L"),
        path("corner_spiral_L", [(145,135),(150,110),(160,90),(180,80),(200,85),(212,102),(210,122),(198,138),(180,143),(163,135),(157,120),(165,106),(180,103),(189,112),(188,123),(180,128)], "CORNER_JOIN_L", "CORNER_TIP_L"),
        path("corner_bridge_L", [(145,135),(150,160),(175,177),(205,185),(240,190),(274,205)], "CORNER_JOIN_L", "TOP_SIDE_L"),
        path("lower_corner_spiral_L", [(225,480),(205,490),(182,495),(160,489),(145,472),(145,448),(155,430),(175,420),(195,425),(205,440),(203,456),(190,465),(176,460),(171,450)], "LOW_SIDE_L", "LOW_CORNER_TIP_L"),
        path("lower_foot_L", [(160,500),(180,490),(210,488),(238,500),(247,508)], "LOW_FOOT_L", "LOW_FOOT_TIP_L"),
    ]


def _swap_suffix(value):
    text = str(value)
    return text[:-2] + "_R" if text.endswith("_L") else text


def _mirror_record(rec, central_nodes=("C_UP", "C_LOW")):
    out = {k: v for k, v in rec.items()
           if k not in ("points_px", "start_node", "end_node", "name", "node_ids")}
    out["name"] = _swap_suffix(rec["name"])
    out["points_px"] = [[round(2*AXIS_PX - float(x), 3), float(y)]
                         for x, y in rec["points_px"]]
    def mirror_node(node):
        if node is None:
            return None
        return node if node in central_nodes else _swap_suffix(node)
    for key in ("start_node", "end_node"):
        if key in rec:
            out[key] = mirror_node(rec[key])
    if "node_ids" in rec:
        out["node_ids"] = [mirror_node(node) for node in rec["node_ids"]]
    return out


def upper_pixel_paths():
    left = _upper_left()
    right = [_mirror_record(rec) for rec in left]
    return left + right


def upper_node_points():
    left = {
        "C_UP": (512,200), "C_LOW": (512,434),
        "HEART_INNER_TIP_L": (462,196), "HEART_LOWER_BRANCH_L": (500,395),
        "HEART_LOWER_TIP_L": (466,333), "LOW_BIG_TIP_L": (403,454),
        "LOW_MID_L": (412,398), "LOW_MID_TIP_L": (335,365),
        "LOW_MID_BRANCH_L": (350,408), "LOW_SMALL_TIP_L": (404,435),
        "TOP_LOBE_L": (300,210), "TOP_LEAF_BASE_L": (360,165), "TOP_LOBE_TIP_L": (328,135),
        "TOP_LEAF_TIP_L": (400,105), "DIAG_LOW_L": (500,420),
        "TOP_SIDE_L": (274,205), "SIDE_CURL_NODE_L": (210,322),
        "SIDE_LOBE_TIP_L": (188,278), "SIDE_SMALL_TIP_L": (210,370),
        "LOW_SIDE_L": (225,480), "CORNER_JOIN_L": (145,135),
        "CORNER_TIP_L": (180,128), "LOW_CORNER_TIP_L": (171,450),
        "LOW_FOOT_L": (160,500), "LOW_FOOT_TIP_L": (247,508),
    }
    out = dict(left)
    for key, (x, y) in left.items():
        if key in ("C_UP", "C_LOW"):
            continue
        out[_swap_suffix(key)] = (2*AXIS_PX-x, y)
    return out


def lower_bay_left_paths():
    return [
        path("bay_stem_L", [(238,528),(230,555),(218,590),(202,625),(190,660),(183,695),(175,730),(162,770),(153,815),(148,855),(151,900)], "BAY_TOP_L", "BAY_BOTTOM_L", anchor_nodes={5: "BAY_MID_L", 7: "BAY_LOWER_L"}),
        path("bay_top_curl_L", [(238,528),(220,520),(198,516),(176,522),(160,538),(160,558),(175,575),(195,577),(210,565),(211,548),(202,536),(188,534),(179,543)], "BAY_TOP_L", "BAY_TOP_TIP_L"),
        path("bay_top_bridge_L", [(191,520),(210,520),(225,523),(238,528)], "BAY_TOP_END_L", "BAY_TOP_L"),
        path("bay_mid_small_L", [(183,695),(170,680),(157,680),(150,692),(157,705),(172,708),(181,698),(176,688),(166,687)], "BAY_MID_L", "BAY_MID_SMALL_TIP_L"),
        path("bay_mid_big_L", [(183,695),(202,706),(220,720),(230,738),(228,756),(214,768),(195,765),(181,752),(180,735),(190,722),(204,721),(212,729)], "BAY_MID_L", "BAY_MID_BIG_TIP_L"),
        path("bay_lower_small_L", [(162,770),(175,784),(188,798),(187,813),(177,824),(164,822),(159,812),(165,803),(176,806),(180,814)], "BAY_LOWER_L", "BAY_LOWER_SMALL_TIP_L"),
        path("bay_bottom_big_L", [(153,815),(170,825),(195,840),(215,858),(220,882),(211,905),(191,920),(168,918),(151,904),(147,881),(153,858),(171,847),(190,852),(198,866),(194,880),(182,887)], "BAY_LOWER_L", "BAY_BOTTOM_TIP_L"),
        path("bay_bottom_end_L", [(151,900),(165,905),(180,906),(193,889)], "BAY_BOTTOM_L", "BAY_END_L"),
    ]


def lower_node_points():
    return {
        "BAY_TOP_L": (238,528), "BAY_TOP_END_L": (191,520),
        "BAY_TOP_TIP_L": (179,543), "BAY_MID_L": (183,695),
        "BAY_MID_SMALL_TIP_L": (166,687), "BAY_MID_BIG_TIP_L": (212,729),
        "BAY_LOWER_L": (162,770), "BAY_LOWER_SMALL_TIP_L": (180,814),
        "BAY_BOTTOM_L": (151,900), "BAY_BOTTOM_TIP_L": (182,887),
        "BAY_END_L": (193,889),
    }


def mirror_paths(paths):
    return [_mirror_record(rec, central_nodes=()) for rec in paths]


def mirrored_node_points(points):
    out = dict(points)
    for key, (x, y) in points.items():
        out[_swap_suffix(key)] = (2*AXIS_PX-x, y)
    return out


def project_network(paths, node_points, ref_name=REF_NAME, mirror=False,
                    mirror_axis_px=AXIS_PX, depth_offset=DEPTH_OFFSET):
    """Project pixel paths and preserve internal shared-node ids for the mesh builder."""
    from reference_curve_mapping import project_paths_to_world
    branch_nodes = [{"id": key, "point_px": [float(pt[0]), float(pt[1])]}
                    for key, pt in node_points.items()]
    projected = project_paths_to_world(
        paths, ref_name=ref_name, branch_nodes=branch_nodes,
        mirror=mirror, mirror_axis_px=mirror_axis_px,
        depth_offset=depth_offset,
    )
    for source, target in zip(paths, projected["paths"]):
        if "node_ids" in source:
            target["node_ids"] = list(source["node_ids"])
    shared = {record["id"]: tuple(record["point_world"])
              for record in projected["branch_nodes"] if record.get("id")}
    return projected["paths"], shared
