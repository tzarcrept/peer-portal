/*
 * S-curve renderer.
 *
 * Draws the target (planned) and current (actual) cumulative-progress curves as a
 * single inline SVG. Written against the DOM directly with no charting library and
 * no CDN, because the portal has to run on machines with no internet access.
 *
 * The shaded band between the two curves is the point of the chart. A number saying
 * "-35.7 points behind" is easy to skim past; the area between where the project
 * should be and where it is makes the same fact impossible to miss, and shows when
 * the gap opened rather than just how wide it is now.
 *
 * Data arrives from Django via {{ ... |json_script:"..." }}, so nothing here needs to
 * parse or trust a network response.
 */

(function () {
    "use strict";

    var NS = "http://www.w3.org/2000/svg";

    function svgEl(name, attrs) {
        var node = document.createElementNS(NS, name);
        for (var key in attrs) {
            if (Object.prototype.hasOwnProperty.call(attrs, key)) {
                node.setAttribute(key, attrs[key]);
            }
        }
        return node;
    }

    function parseDate(text) {
        var parts = String(text).split("-");
        return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    }

    function formatTick(dateObj) {
        var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        return months[dateObj.getMonth()] + " " + String(dateObj.getFullYear()).slice(2);
    }

    function render(container) {
        var payloadId = container.getAttribute("data-source");
        var node = document.getElementById(payloadId);
        if (!node) { return; }

        var data;
        try {
            data = JSON.parse(node.textContent);
        } catch (err) {
            container.textContent = "Chart data could not be read.";
            return;
        }
        var points = (data && data.points) || [];
        if (points.length < 2) {
            container.innerHTML = '<p class="caption">Not enough scheduled activity to plot a curve. ' +
                                  'Add planned start and finish dates to the project\'s activities.</p>';
            return;
        }

        var W = 900, H = 360;
        var ML = 48, MR = 16, MT = 14, MB = 40;
        var plotW = W - ML - MR;
        var plotH = H - MT - MB;

        var first = parseDate(points[0].date).getTime();
        var last = parseDate(points[points.length - 1].date).getTime();
        var span = Math.max(last - first, 1);

        function x(dateText) {
            return ML + (parseDate(dateText).getTime() - first) / span * plotW;
        }
        function y(value) {
            return MT + (1 - value / 100) * plotH;
        }

        var svg = svgEl("svg", {
            viewBox: "0 0 " + W + " " + H,
            preserveAspectRatio: "xMidYMid meet",
            role: "img",
            "aria-label": "Planned versus actual cumulative progress"
        });

        // ---- Drafting grid + y axis ----
        var grid = svgEl("g", {});
        [0, 25, 50, 75, 100].forEach(function (level) {
            var yy = y(level);
            grid.appendChild(svgEl("line", {
                x1: ML, y1: yy, x2: W - MR, y2: yy,
                stroke: level === 0 ? "#c3ccd6" : "#eaeef3",
                "stroke-width": 1
            }));
            var label = svgEl("text", {
                x: ML - 9, y: yy + 4, "text-anchor": "end",
                "font-size": "11", "font-family": "ui-monospace, Consolas, monospace",
                fill: "#8894a2"
            });
            label.textContent = level + "%";
            grid.appendChild(label);
        });
        svg.appendChild(grid);

        // ---- X axis ticks: about six evenly spaced dates ----
        var tickCount = Math.min(6, points.length);
        var stride = Math.max(1, Math.floor((points.length - 1) / (tickCount - 1)));
        for (var i = 0; i < points.length; i += stride) {
            var tx = x(points[i].date);
            svg.appendChild(svgEl("line", {
                x1: tx, y1: MT, x2: tx, y2: MT + plotH,
                stroke: "#f2f5f8", "stroke-width": 1
            }));
            var tick = svgEl("text", {
                x: tx, y: H - MB + 18, "text-anchor": "middle",
                "font-size": "11", "font-family": "ui-monospace, Consolas, monospace",
                fill: "#8894a2"
            });
            tick.textContent = formatTick(parseDate(points[i].date));
            svg.appendChild(tick);
        }

        // ---- Variance band: planned out, actual back ----
        var actualPoints = points.filter(function (p) { return p.actual !== null && p.actual !== undefined; });
        if (actualPoints.length > 1) {
            var forward = actualPoints.map(function (p) { return x(p.date) + "," + y(p.planned); });
            var back = actualPoints.slice().reverse().map(function (p) { return x(p.date) + "," + y(p.actual); });
            svg.appendChild(svgEl("polygon", {
                points: forward.concat(back).join(" "),
                fill: "rgba(199, 62, 62, 0.13)",
                stroke: "none"
            }));
        }

        // ---- Planned (target) curve ----
        svg.appendChild(svgEl("polyline", {
            points: points.map(function (p) { return x(p.date) + "," + y(p.planned); }).join(" "),
            fill: "none", stroke: "#2f6fb0", "stroke-width": 2,
            "stroke-dasharray": "6 4", "stroke-linejoin": "round"
        }));

        // ---- Actual (current) curve, stopping at today ----
        if (actualPoints.length > 1) {
            svg.appendChild(svgEl("polyline", {
                points: actualPoints.map(function (p) { return x(p.date) + "," + y(p.actual); }).join(" "),
                fill: "none", stroke: "#16202b", "stroke-width": 2.4,
                "stroke-linejoin": "round", "stroke-linecap": "round"
            }));
            var tip = actualPoints[actualPoints.length - 1];
            svg.appendChild(svgEl("circle", {
                cx: x(tip.date), cy: y(tip.actual), r: 3.5,
                fill: "#16202b", stroke: "#ffffff", "stroke-width": 1.5
            }));
        }

        // ---- Today rule ----
        if (data.today) {
            var todayMs = parseDate(data.today).getTime();
            if (todayMs >= first && todayMs <= last) {
                var tX = x(data.today);
                svg.appendChild(svgEl("line", {
                    x1: tX, y1: MT - 4, x2: tX, y2: MT + plotH,
                    stroke: "#b3322c", "stroke-width": 1, "stroke-dasharray": "3 3"
                }));
                var todayLabel = svgEl("text", {
                    x: tX + 5, y: MT + 8,
                    "font-size": "10", "font-family": "ui-monospace, Consolas, monospace",
                    "letter-spacing": "1", fill: "#b3322c"
                });
                todayLabel.textContent = "TODAY";
                svg.appendChild(todayLabel);
            }
        }

        // ---- Hover readout ----
        var hover = svgEl("g", { opacity: "0", "pointer-events": "none" });
        var hoverLine = svgEl("line", {
            y1: MT, y2: MT + plotH, stroke: "#8894a2", "stroke-width": 1
        });
        var hoverBox = svgEl("rect", {
            width: 168, height: 56, rx: 4,
            fill: "#ffffff", stroke: "#d9e0e8", "stroke-width": 1
        });
        var lineDate = svgEl("text", {
            "font-size": "11", "font-family": "ui-monospace, Consolas, monospace", fill: "#16202b"
        });
        var linePlanned = svgEl("text", {
            "font-size": "11", "font-family": "ui-monospace, Consolas, monospace", fill: "#2f6fb0"
        });
        var lineActual = svgEl("text", {
            "font-size": "11", "font-family": "ui-monospace, Consolas, monospace", fill: "#16202b"
        });
        hover.appendChild(hoverLine);
        hover.appendChild(hoverBox);
        hover.appendChild(lineDate);
        hover.appendChild(linePlanned);
        hover.appendChild(lineActual);
        svg.appendChild(hover);

        var capture = svgEl("rect", {
            x: ML, y: MT, width: plotW, height: plotH, fill: "transparent"
        });
        svg.appendChild(capture);

        capture.addEventListener("mousemove", function (event) {
            var box = svg.getBoundingClientRect();
            var px = (event.clientX - box.left) / box.width * W;

            var nearest = points[0], bestGap = Infinity;
            points.forEach(function (p) {
                var gap = Math.abs(x(p.date) - px);
                if (gap < bestGap) { bestGap = gap; nearest = p; }
            });

            var nx = x(nearest.date);
            hoverLine.setAttribute("x1", nx);
            hoverLine.setAttribute("x2", nx);

            var boxX = nx + 12;
            if (boxX + 168 > W - MR) { boxX = nx - 180; }
            hoverBox.setAttribute("x", boxX);
            hoverBox.setAttribute("y", MT + 8);

            lineDate.setAttribute("x", boxX + 10);
            lineDate.setAttribute("y", MT + 25);
            lineDate.textContent = nearest.date;

            linePlanned.setAttribute("x", boxX + 10);
            linePlanned.setAttribute("y", MT + 40);
            linePlanned.textContent = "Target  " + nearest.planned.toFixed(1) + "%";

            lineActual.setAttribute("x", boxX + 10);
            lineActual.setAttribute("y", MT + 54);
            lineActual.textContent = nearest.actual === null || nearest.actual === undefined
                ? "Current    --"
                : "Current " + nearest.actual.toFixed(1) + "%";

            hover.setAttribute("opacity", "1");
        });

        capture.addEventListener("mouseleave", function () {
            hover.setAttribute("opacity", "0");
        });

        container.innerHTML = "";
        container.appendChild(svg);
    }

    document.addEventListener("DOMContentLoaded", function () {
        var targets = document.querySelectorAll("[data-chart='s-curve']");
        Array.prototype.forEach.call(targets, function (container) {
            try {
                render(container);
            } catch (err) {
                container.innerHTML = '<p class="caption">Chart could not be drawn.</p>';
            }
        });
    });
})();
