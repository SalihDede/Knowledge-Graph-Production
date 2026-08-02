"""
Bilgi grafı HTML üretici.
Wikontic'teki visualize_knowledge_graph() fonksiyonunun birebir kopyası;
Streamlit bağımlılığı olmadan saf HTML string döndürür.
"""

import os
import tempfile
from pyvis.network import Network

# ── Renk paleti (Wikontic ile aynı) ──────────────────────────────────────────
COLOR_DEFAULT     = "#C7C8CC"   # gri  – normal düğümler
COLOR_HIGHLIGHT   = "#B2CD9C"   # yeşil – vurgulanan düğümler
COLOR_EDGE        = "#000000"   # siyah – tüm kenarlar
SOURCE_COLORS     = ["#1f7a70", "#2563c9", "#9a6b00"]
SHARED_COLORS     = ["#6b4bd6", "#0f7f8f", "#9b4a8a", "#547025", "#9a4f12"]

# Ontoloji grafı renkleri
COLOR_ONT_CENTER  = "#4A90D9"   # mavi  – merkez varlık
COLOR_ONT_PARENT  = "#F5A623"   # turuncu – ebeveyn varlıklar
COLOR_ONT_SUBJ    = "#5CB85C"   # yeşil – subject property
COLOR_ONT_OBJ     = "#9B59B6"   # mor   – object property


_FILL_CSS = """
<style>
  html, body {
    margin: 0; padding: 0;
    width: 100%; height: 100%;
    overflow: hidden;
  }
  .card {
    width: 100% !important;
    height: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
  }
  #mynetwork {
    width: 100% !important;
    height: 100% !important;
  }
</style>"""


def _net_to_html(net: Network) -> str:
    """Pyvis Network → HTML string. iframe'i tamamen dolduracak CSS enjekte eder."""
    try:
        html = net.generate_html()
    except AttributeError:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmp:
            net.save_graph(tmp.name)
            path = tmp.name
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        os.remove(path)

    # <head> kapanmadan önce fill CSS'i enjekte et
    html = html.replace("</head>", _FILL_CSS + "\n</head>", 1)
    return html


def build_graph_html(
    triplets: list[dict],
    highlight_entities: list[str] | None = None,
    height: str = "100%",
) -> str:
    """
    Triplet listesinden interaktif graf HTML'i üretir.

    Parameters
    ----------
    triplets : [{"baş": ..., "baş_tipi": ..., "ilişki": ..., "uç": ..., "uç_tipi": ...}, ...]
    highlight_entities : vurgulanacak düğüm adları (yeşil gösterilir)
    height : iframe yüksekliği (varsayılan "100%")

    Returns
    -------
    Tam HTML string (vis-network.js gömülü, self-contained)
    """
    net = Network(
        height=height,
        width="100%",
        bgcolor="#ffffff",
        font_color="black",
        directed=True,
    )

    h_set = set(highlight_entities or [])
    added_nodes: set[str] = set()

    for t in triplets:
        s = str(t.get("baş", "") or "")
        r = str(t.get("ilişki", "") or "")
        o = str(t.get("uç", "") or "")
        if not s or not o:
            continue
        for node in (s, o):
            if node not in added_nodes:
                color = COLOR_HIGHLIGHT if node in h_set else COLOR_DEFAULT
                net.add_node(node, label=node, color=color)
                added_nodes.add(node)
        net.add_edge(s, o, label=r, color=COLOR_EDGE)

    return _net_to_html(net)


def _normalize_text(value) -> str:
    return str(value or "").strip()


def _triple_key(triplet: dict) -> str:
    return "||".join([
        _normalize_text(triplet.get("baş")).casefold(),
        _normalize_text(triplet.get("ilişki")).casefold(),
        _normalize_text(triplet.get("uç")).casefold(),
    ])


def _source_combo_label(source_ids: list[str], source_map: dict[str, dict]) -> str:
    letters = [
        _normalize_text(source_map.get(source_id, {}).get("source_letter"))
        for source_id in source_ids
    ]
    letters = [letter for letter in letters if letter]
    if not letters:
        return "Source"
    return f"Source {'+'.join(letters)}"


def build_source_graph_html(
    sources: list[dict],
    height: str = "100%",
) -> str:
    """Builds a PyVis/vis-network provenance graph with the same interaction model as slot graphs."""
    net = Network(
        height=height,
        width="100%",
        bgcolor="#fbfdfc",
        font_color="#171f1d",
        directed=True,
    )

    source_map = {}
    for index, source in enumerate(sources):
        source_id = _normalize_text(source.get("id")) or f"source-{index}"
        source_map[source_id] = {
            **source,
            "id": source_id,
            "color": SOURCE_COLORS[index % len(SOURCE_COLORS)],
        }

    edge_map: dict[str, dict] = {}
    node_degree: dict[str, int] = {}

    for source_id, source in source_map.items():
        seen = set()
        for triplet in source.get("triplets", []) or []:
            subject = _normalize_text(triplet.get("baş"))
            relation = _normalize_text(triplet.get("ilişki"))
            obj = _normalize_text(triplet.get("uç"))
            if not subject or not obj:
                continue

            key = _triple_key(triplet)
            if not key or key == "||||" or key in seen:
                continue
            seen.add(key)

            node_degree[subject] = node_degree.get(subject, 0) + 1
            node_degree[obj] = node_degree.get(obj, 0) + 1

            if key not in edge_map:
                edge_map[key] = {
                    "subject": subject,
                    "relation": relation,
                    "object": obj,
                    "sources": [],
                    "source_ids": [],
                }

            if source_id not in edge_map[key]["source_ids"]:
                edge_map[key]["source_ids"].append(source_id)
                edge_map[key]["sources"].append(source)

    for node, degree in node_degree.items():
        is_hub = degree >= 3
        net.add_node(
            node,
            label=node,
            title=node,
            color={
                "background": "#ffffff" if not is_hub else "#dff3ee",
                "border": "#1f7a70",
                "highlight": {"background": "#c6ebe2", "border": "#0d5e54"},
            },
            borderWidth=2,
            size=min(40, max(19, 15 + degree * 2)),
            font={"size": 17 if is_hub else 15, "face": "Inter", "bold": is_hub},
        )

    combo_colors: dict[str, str] = {}
    pair_counts: dict[tuple[str, str], int] = {}
    for edge_index, edge in enumerate(edge_map.values()):
        source_ids = edge["source_ids"]
        combo_id = "+".join(source_ids)
        if combo_id not in combo_colors:
            if len(source_ids) == 1:
                combo_colors[combo_id] = source_map.get(source_ids[0], {}).get("color", SOURCE_COLORS[0])
            else:
                combo_colors[combo_id] = SHARED_COLORS[(len(combo_colors) - len(source_map)) % len(SHARED_COLORS)]

        combo_label = _source_combo_label(source_ids, source_map)
        source_details = "<br>".join(
            [
                f"{_normalize_text(source.get('graph_label')) or combo_label}"
                f" / {_normalize_text(source.get('kg_label')) or '-'}"
                f" / {_normalize_text(source.get('prompt_label')) or '-'}"
                for source in edge["sources"]
            ]
        )
        title = (
            f"<strong>{edge['subject']}</strong> → "
            f"{edge['relation'] or 'relation'} → "
            f"<strong>{edge['object']}</strong><br><br>"
            f"<strong>{combo_label}</strong><br>{source_details}"
        )

        pair_key = (edge["subject"], edge["object"])
        pair_index = pair_counts.get(pair_key, 0)
        pair_counts[pair_key] = pair_index + 1
        smooth_type = "curvedCW" if pair_index % 2 == 0 else "curvedCCW"
        roundness = 0.14 + min(pair_index, 4) * 0.08
        edge_id = f"edge-{edge_index}"

        net.add_edge(
            edge["subject"],
            edge["object"],
            id=edge_id,
            label=edge["relation"] or combo_label,
            title=title,
            color={"color": combo_colors[combo_id], "highlight": combo_colors[combo_id]},
            width=3.0 if len(source_ids) == 1 else 4.2,
            arrows={"to": {"enabled": True, "scaleFactor": 0.84}},
            smooth={"enabled": True, "type": smooth_type, "roundness": roundness},
            font={
                "size": 15,
                "face": "Inter",
                "align": "middle",
                "strokeWidth": 7,
                "strokeColor": "#ffffff",
            },
            sourceIds=source_ids,
            comboId=combo_id,
            comboLabel=combo_label,
            baseColor=combo_colors[combo_id],
        )

    net.set_options("""
    {
      "interaction": {
        "dragNodes": true,
        "dragView": true,
        "zoomView": true,
        "hover": true,
        "tooltipDelay": 120,
        "navigationButtons": false,
        "keyboard": {
          "enabled": true,
          "bindToWindow": false
        }
      },
      "physics": {
        "enabled": true,
        "solver": "forceAtlas2Based",
        "forceAtlas2Based": {
          "gravitationalConstant": -92,
          "centralGravity": 0.008,
          "springLength": 240,
          "springConstant": 0.055,
          "damping": 0.62,
          "avoidOverlap": 1
        },
        "stabilization": {
          "enabled": true,
          "iterations": 260,
          "fit": true
        }
      },
      "nodes": {
        "shape": "dot",
        "shadow": false
      },
      "edges": {
        "smooth": {
          "enabled": true
        },
        "selectionWidth": 2.2
      }
    }
    """)

    html = _net_to_html(net)
    html = html.replace(
        "</body>",
        """
<script>
  (function () {
    if (
      typeof network === "undefined" ||
      typeof nodes === "undefined" ||
      typeof edges === "undefined"
    ) {
      return;
    }

    var baseNodes = {};
    var baseEdges = {};

    function clone(value) {
      if (value === undefined || value === null) return value;
      return JSON.parse(JSON.stringify(value));
    }

    function asArray(value) {
      if (Array.isArray(value)) return value.map(String);
      if (value === undefined || value === null || value === "") return [];
      return String(value).split(",").filter(Boolean);
    }

    function rememberBaseState() {
      nodes.get().forEach(function (node) {
        baseNodes[node.id] = {
          color: clone(node.color),
          font: clone(node.font),
          borderWidth: node.borderWidth,
          size: node.size
        };
      });

      edges.get().forEach(function (edge) {
        baseEdges[edge.id] = {
          color: clone(edge.color),
          font: clone(edge.font),
          width: edge.width,
          arrows: clone(edge.arrows),
          smooth: clone(edge.smooth)
        };
      });
    }

    function hasIntersection(left, right) {
      var lookup = {};
      right.forEach(function (item) {
        lookup[item] = true;
      });
      return left.some(function (item) {
        return lookup[item];
      });
    }

    function notifyParent(target) {
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: "sourceGraphFocusChanged", target: target }, "*");
      }
    }

    function targetFromEdge(edge) {
      var sourceIds = asArray(edge.sourceIds);
      if (sourceIds.length === 1) {
        return { mode: "source", id: sourceIds[0] };
      }
      return { mode: "combo", id: edge.comboId || sourceIds.join("+") };
    }

    function resetFocus(notify) {
      nodes.update(nodes.get().map(function (node) {
        var base = baseNodes[node.id] || {};
        return {
          id: node.id,
          color: clone(base.color),
          font: clone(base.font),
          borderWidth: base.borderWidth,
          size: base.size
        };
      }));

      edges.update(edges.get().map(function (edge) {
        var base = baseEdges[edge.id] || {};
        return {
          id: edge.id,
          color: clone(base.color),
          font: clone(base.font),
          width: base.width,
          arrows: clone(base.arrows),
          smooth: clone(base.smooth)
        };
      }));

      if (notify) notifyParent(null);
    }

    function applyFocus(edgePredicate, centerNodeId, shouldFit, target) {
      var activeEdgeIds = {};
      var activeNodeIds = {};
      var activeEdgeCount = 0;

      edges.get().forEach(function (edge) {
        if (!edgePredicate(edge)) return;
        activeEdgeIds[edge.id] = true;
        activeNodeIds[edge.from] = true;
        activeNodeIds[edge.to] = true;
        activeEdgeCount += 1;
      });

      if (centerNodeId) activeNodeIds[centerNodeId] = true;
      if (activeEdgeCount === 0 && !centerNodeId) {
        resetFocus(false);
        return;
      }

      nodes.update(nodes.get().map(function (node) {
        var base = baseNodes[node.id] || {};
        var baseFont = clone(base.font) || {};
        var isActive = Boolean(activeNodeIds[node.id]);

        if (isActive) {
          baseFont.color = "#111817";
          return {
            id: node.id,
            color: clone(base.color),
            font: baseFont,
            borderWidth: Math.max(base.borderWidth || 2, 3),
            size: Math.min(48, (base.size || node.size || 19) + 5)
          };
        }

        baseFont.color = "rgba(77, 91, 88, 0.34)";
        return {
          id: node.id,
          color: {
            background: "#f1f5f4",
            border: "#d2dcda",
            highlight: { background: "#f1f5f4", border: "#d2dcda" }
          },
          font: baseFont,
          borderWidth: 1,
          size: Math.max(13, (base.size || node.size || 19) - 3)
        };
      }));

      edges.update(edges.get().map(function (edge) {
        var base = baseEdges[edge.id] || {};
        var baseFont = clone(base.font) || {};
        var isActive = Boolean(activeEdgeIds[edge.id]);

        if (isActive) {
          baseFont.color = "#111817";
          baseFont.size = Math.max(16, baseFont.size || 15);
          baseFont.strokeWidth = 8;
          baseFont.strokeColor = "#ffffff";
          return {
            id: edge.id,
            color: clone(base.color),
            font: baseFont,
            width: Math.max(5.5, (base.width || edge.width || 3) + 2.2),
            arrows: clone(base.arrows),
            smooth: clone(base.smooth)
          };
        }

        baseFont.color = "rgba(77, 91, 88, 0.2)";
        baseFont.strokeColor = "rgba(255, 255, 255, 0.76)";
        return {
          id: edge.id,
          color: {
            color: "rgba(130, 142, 140, 0.15)",
            highlight: "rgba(130, 142, 140, 0.22)",
            hover: "rgba(130, 142, 140, 0.22)"
          },
          font: baseFont,
          width: 1,
          arrows: clone(base.arrows),
          smooth: clone(base.smooth)
        };
      }));

      var focusedNodes = Object.keys(activeNodeIds);
      if (shouldFit && focusedNodes.length > 0 && focusedNodes.length <= 40) {
        network.fit({
          nodes: focusedNodes,
          animation: { duration: 360, easingFunction: "easeInOutQuad" }
        });
      }

      if (target) notifyParent(target);
    }

    function focusSource(sourceId, shouldFit, shouldNotify) {
      var target = { mode: "source", id: String(sourceId) };
      applyFocus(function (edge) {
        return asArray(edge.sourceIds).indexOf(String(sourceId)) !== -1;
      }, null, shouldFit, shouldNotify ? target : null);
    }

    function focusCombo(comboId, shouldFit, shouldNotify) {
      var target = { mode: "combo", id: String(comboId) };
      applyFocus(function (edge) {
        return String(edge.comboId || "") === String(comboId);
      }, null, shouldFit, shouldNotify ? target : null);
    }

    function focusEdge(edgeId, shouldFit) {
      var edge = edges.get(edgeId);
      if (!edge) return;
      var targetSources = asArray(edge.sourceIds);
      var target = targetFromEdge(edge);
      applyFocus(function (candidate) {
        return candidate.id === edgeId || hasIntersection(asArray(candidate.sourceIds), targetSources);
      }, null, shouldFit, target);
    }

    function focusNode(nodeId, shouldFit) {
      applyFocus(function (edge) {
        return edge.from === nodeId || edge.to === nodeId;
      }, nodeId, shouldFit, null);
    }

    rememberBaseState();

    window.addEventListener("message", function (event) {
      var data = event.data || {};
      if (data.type !== "sourceGraphFocus") return;

      if (data.mode === "source" && data.id) {
        focusSource(data.id, true, false);
      } else if (data.mode === "combo" && data.id) {
        focusCombo(data.id, true, false);
      } else if (data.mode === "edge" && data.id) {
        focusEdge(data.id, true);
      } else if (data.mode === "reset") {
        resetFocus(false);
      }
    });

    network.on("click", function (params) {
      if (params.edges && params.edges.length > 0) {
        focusEdge(params.edges[0], true);
        return;
      }
      if (params.nodes && params.nodes.length > 0) {
        focusNode(params.nodes[0], true);
        return;
      }
      resetFocus(true);
    });

    network.once("stabilizationIterationsDone", function () {
      network.setOptions({ physics: false });
      network.fit({ animation: { duration: 320, easingFunction: "easeInOutQuad" } });
    });
  }());
</script>
</body>
""",
        1,
    )
    return html


def build_ontology_graph_html(
    neighborhood: dict,
    height: str = "100%",
) -> str:
    """
    Wikidata ontoloji komşuluğunu görselleştirir.
    Wikontic'teki visualize_ontology_neighborhood() fonksiyonunun kopyası.

    neighborhood = {
        "center":  {"id": "Q5", "label": "human"},
        "parents": [{"id": "Q215627", "label": "person"}, ...],
        "properties": [{"id": "P31", "label": "instance of", "direction": "subject"}, ...]
    }
    """
    net = Network(
        height=height,
        width="100%",
        bgcolor="#ffffff",
        font_color="black",
        directed=True,
    )

    center = neighborhood["center"]
    net.add_node(
        center["id"],
        label=f"{center['label']}\n({center['id']})",
        color=COLOR_ONT_CENTER,
        size=25,
    )

    for parent in neighborhood.get("parents", []):
        net.add_node(
            parent["id"],
            label=f"{parent['label']}\n({parent['id']})",
            color=COLOR_ONT_PARENT,
            size=18,
        )
        net.add_edge(center["id"], parent["id"], label="is a",
                     color=COLOR_ONT_PARENT, dashes=True)

    for prop in neighborhood.get("properties", []):
        prop_node_id = f"prop_{prop['id']}"
        color = COLOR_ONT_SUBJ if prop["direction"] == "subject" else COLOR_ONT_OBJ
        direction_label = "→ subject" if prop["direction"] == "subject" else "← object"
        net.add_node(
            prop_node_id,
            label=f"{prop['label']}\n({prop['id']})\n{direction_label}",
            color=color,
            size=14,
            shape="box",
        )
        net.add_edge(center["id"], prop_node_id, label=prop["label"], color=color)

    return _net_to_html(net)
