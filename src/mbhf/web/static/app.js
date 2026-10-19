(function () {
  "use strict";

  // Several files: one row per file, each with what it contains.
  var rows = document.getElementById("file-rows");
  var add = document.getElementById("add-file");
  if (rows && add) {
    add.hidden = false;
    add.addEventListener("click", function () {
      var n = rows.children.length;
      var copy = rows.firstElementChild.cloneNode(true);
      var file = copy.querySelector("input[type=file]");
      var mode = copy.querySelector("select");
      file.id = "track-" + n;
      file.value = "";
      file.required = false;
      copy.querySelector("label[for^=track]").setAttribute("for", file.id);
      mode.id = "mode-" + n;
      mode.selectedIndex = 0;
      copy.querySelector("label[for^=mode]").setAttribute("for", mode.id);
      rows.appendChild(copy);
      file.focus();
    });
  }

  // Show that work is happening: the analysis takes a few seconds.
  var form = document.getElementById("upload-form");
  if (form) {
    form.addEventListener("submit", function () {
      var button = document.getElementById("submit");
      var busy = document.getElementById("busy");
      if (busy) busy.hidden = false;
      if (button) {
        button.disabled = true;
        button.textContent = "Analysing…";
      }
    });
  }

  // Result page: download the data as a file, built in the browser from the page itself.
  var dl = document.getElementById("download-json");
  var holder = document.getElementById("result-json");
  if (dl && holder) {
    dl.addEventListener("click", function () {
      var blob = new Blob([JSON.stringify(JSON.parse(holder.textContent), null, 2)], { type: "application/json" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "mont-blanc-track-result.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    });
  }
})();
