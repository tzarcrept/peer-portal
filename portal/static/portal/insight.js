/*
 * Regenerate-insights button.
 *
 * Posts to the refresh endpoint, which bypasses the insight cache and forces a fresh
 * narrative. The endpoint is written so it always returns JSON with HTTP 200 even when
 * the model call fails, so the only thing handled here is a genuinely broken request
 * (no network to the local server at all). In every other case the server returns a
 * usable insight -- rule-based if the model was unavailable -- and the panel updates
 * normally rather than showing an error.
 */

(function () {
    "use strict";

    function getCookie(name) {
        var match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
        return match ? decodeURIComponent(match.pop()) : "";
    }

    function renderList(node, items, emptyText) {
        node.innerHTML = "";
        if (!items || !items.length) {
            var blank = document.createElement("li");
            var blankSpan = document.createElement("span");
            blankSpan.textContent = emptyText;
            blank.appendChild(blankSpan);
            node.appendChild(blank);
            return;
        }
        items.forEach(function (item) {
            var li = document.createElement("li");
            var title = document.createElement("strong");
            title.textContent = item.title || "";
            var detail = document.createElement("span");
            detail.textContent = item.detail || "";
            li.appendChild(title);
            li.appendChild(detail);
            node.appendChild(li);
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        var button = document.getElementById("refresh-insight");
        if (!button) { return; }

        button.addEventListener("click", function () {
            var target = button.getAttribute("data-target");
            if (!target) { return; }

            var originalLabel = button.textContent;
            button.disabled = true;
            button.textContent = "Regenerating…";

            fetch("/insight/" + encodeURIComponent(target) + "/refresh/", {
                method: "POST",
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "Content-Type": "application/json"
                }
            })
                .then(function (response) { return response.json(); })
                .then(function (payload) {
                    if (!payload.ok || !payload.insight) {
                        throw new Error(payload.error || "no insight returned");
                    }
                    var insight = payload.insight;
                    var panel = document.querySelector(".insight");

                    var summary = document.querySelector("[data-insight-summary]");
                    if (summary) { summary.textContent = insight.summary; }

                    renderList(document.querySelector("[data-insight-risks]"),
                               insight.risks, "No risks flagged.");
                    renderList(document.querySelector("[data-insight-actions]"),
                               insight.actions, "No actions recommended.");

                    var meta = document.querySelector(".insight-meta");
                    if (meta) {
                        meta.textContent = insight.source_label + " · " + insight.generated_at;
                    }
                    if (panel) {
                        panel.classList.toggle("is-rules", insight.source === "rules");
                    }

                    var note = document.querySelector("[data-insight-note]");
                    if (note) {
                        note.textContent = (insight.reason ? insight.reason + " " : "") +
                            "Every figure referenced above is calculated in portal/analytics.py; " +
                            "the narrative layer interprets those figures and does not compute them.";
                    }
                })
                .catch(function () {
                    var note = document.querySelector("[data-insight-note]");
                    if (note) {
                        note.textContent = "Could not reach the portal to regenerate. " +
                            "The insight shown above is still valid.";
                    }
                })
                .finally(function () {
                    button.disabled = false;
                    button.textContent = originalLabel;
                });
        });
    });
})();
