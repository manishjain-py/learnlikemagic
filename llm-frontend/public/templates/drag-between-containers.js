// ===================================================================
// drag-between-containers — Interactive template for LearnLikeMagic
// ===================================================================
// Runs via: new Function('app', 'PIXI', 'params', code)(app, PIXI, params)
// Canvas: 500 x 350
//
// Params: {
//   title: string,
//   objects: [{ shape, color, label, count }],
//   containers: [{ label, initial }],
//   goal: { [containerLabel]: targetCount },
//   success_message: string
// }
// ===================================================================

// --- Config ---
var W = app.screen.width;
var H = app.screen.height;
var title = params.title || 'Drag to explore!';
var cDefs = params.containers || [];
var oDefs = params.objects || [];
var goal = params.goal || {};
var successMsg = params.success_message || 'Correct!';

var N = cDefs.length || 2;
var PAD = 12;
var HDR = 32;
var FTR = 65;
var CW = (W - PAD * (N + 1)) / N;
var CH = H - HDR - FTR;
var CY = HDR;
var R = Math.min(18, Math.max(12, CW / 8));

// --- State ---
var assign = [];       // objIdx -> containerIdx
var dragObj = null;     // { idx }
var isChecked = false;

// --- Helpers ---
function parseColor(c) {
  if (typeof c === 'number') return c;
  if (typeof c === 'string') return parseInt(c) || 0x4ECDC4;
  return 0x4ECDC4;
}

function drawBox(g, rect, highlight, resultColor) {
  g.clear();
  g.roundRect(rect.x, rect.y, rect.w, rect.h, 10);
  g.fill(resultColor || (highlight ? 0x303055 : 0x252545));
  g.roundRect(rect.x, rect.y, rect.w, rect.h, 10);
  g.stroke({ width: 2, color: highlight ? 0x6C63FF : 0x3a3a5a });
}

function getSlots(ci, count) {
  if (count === 0) return [];
  var rect = cRects[ci];
  var cols = Math.min(count, 3);
  var rows = Math.ceil(count / cols);
  var sp = R * 2 + 8;
  var cx = rect.x + rect.w / 2;
  var cy = rect.y + 26 + (rect.h - 52) / 2;
  var out = [];
  for (var i = 0; i < count; i++) {
    out.push({
      x: cx - ((cols - 1) * sp) / 2 + (i % cols) * sp,
      y: cy - ((rows - 1) * sp) / 2 + Math.floor(i / cols) * sp
    });
  }
  return out;
}

function hitContainer(px, py) {
  for (var i = 0; i < N; i++) {
    var r = cRects[i];
    if (px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h) return i;
  }
  return -1;
}

function layoutAll() {
  var lists = [];
  for (var c = 0; c < N; c++) lists.push([]);
  assign.forEach(function(c, i) { lists[c].push(i); });

  for (var c = 0; c < N; c++) {
    countEls[c].text = String(lists[c].length);
    var slots = getSlots(c, lists[c].length);
    lists[c].forEach(function(oi, si) {
      if (dragObj && dragObj.idx === oi) return;
      objs[oi].position.set(slots[si].x, slots[si].y);
    });
  }
}

function resetAssignments() {
  assign.length = 0;
  for (var d = 0; d < oDefs.length; d++) {
    var cnt = oDefs[d].count || 1;
    for (var j = 0; j < cnt; j++) {
      var placed = -1;
      for (var c = 0; c < N; c++) {
        var already = 0;
        for (var k = 0; k < assign.length; k++) { if (assign[k] === c) already++; }
        if (already < (cDefs[c].initial || 0)) { placed = c; break; }
      }
      assign.push(placed >= 0 ? placed : 0);
    }
  }
}

// --- Title ---
var titleEl = new PIXI.Text({
  text: title,
  style: { fontSize: 15, fill: 0xccccee, fontFamily: 'Arial, sans-serif' }
});
titleEl.anchor.set(0.5, 0);
titleEl.position.set(W / 2, 8);
app.stage.addChild(titleEl);

// --- Containers ---
var cRects = [];
var cBgs = [];
var countEls = [];

for (var i = 0; i < N; i++) {
  var def = cDefs[i] || { label: 'Box ' + (i + 1), initial: 0 };
  var x = PAD + i * (CW + PAD);
  cRects.push({ x: x, y: CY, w: CW, h: CH });

  var bg = new PIXI.Graphics();
  drawBox(bg, cRects[i], false);
  app.stage.addChild(bg);
  cBgs.push(bg);

  var lbl = new PIXI.Text({
    text: def.label,
    style: { fontSize: 12, fill: 0x8888aa, fontFamily: 'Arial, sans-serif' }
  });
  lbl.anchor.set(0.5, 0);
  lbl.position.set(x + CW / 2, CY + 6);
  app.stage.addChild(lbl);

  var ct = new PIXI.Text({
    text: '0',
    style: { fontSize: 22, fill: 0xffffff, fontWeight: 'bold', fontFamily: 'Arial, sans-serif' }
  });
  ct.anchor.set(0.5, 1);
  ct.position.set(x + CW / 2, CY + CH - 5);
  app.stage.addChild(ct);
  countEls.push(ct);
}

// --- Objects ---
var objLayer = new PIXI.Container();
app.stage.addChild(objLayer);
var objs = [];

resetAssignments();

var idx = 0;
for (var d = 0; d < oDefs.length; d++) {
  var def = oDefs[d];
  var cnt = def.count || 1;
  var color = parseColor(def.color);

  for (var j = 0; j < cnt; j++) {
    var gfx = new PIXI.Graphics();
    gfx.circle(0, 0, R);
    gfx.fill(color);
    gfx.circle(0, 0, R);
    gfx.stroke({ width: 1.5, color: 0xffffff, alpha: 0.25 });

    if (def.label) {
      var lt = new PIXI.Text({
        text: def.label,
        style: { fontSize: Math.max(10, R * 0.8), fill: 0xffffff, fontFamily: 'Arial, sans-serif' }
      });
      lt.anchor.set(0.5, 0.5);
      gfx.addChild(lt);
    }

    gfx.eventMode = 'static';
    gfx.cursor = 'pointer';
    gfx.hitArea = new PIXI.Rectangle(-(R + 10), -(R + 10), (R + 10) * 2, (R + 10) * 2);

    (function(thisIdx) {
      gfx.on('pointerdown', function(e) {
        if (isChecked) return;
        dragObj = { idx: thisIdx };
        gfx.alpha = 0.85;
        gfx.scale.set(1.12);
        objLayer.addChild(gfx);
        var pos = e.getLocalPosition(app.stage);
        gfx.position.set(pos.x, pos.y);
      });
    })(idx);

    objLayer.addChild(gfx);
    objs.push(gfx);
    idx++;
  }
}

layoutAll();

// --- Drag handling ---
app.stage.eventMode = 'static';
app.stage.hitArea = new PIXI.Rectangle(0, 0, W, H);

app.stage.on('globalpointermove', function(e) {
  if (!dragObj) return;
  var pos = e.getLocalPosition(app.stage);
  objs[dragObj.idx].position.set(pos.x, pos.y);
  var hover = hitContainer(pos.x, pos.y);
  for (var i = 0; i < N; i++) drawBox(cBgs[i], cRects[i], i === hover);
});

function endDrag(e) {
  if (!dragObj) return;
  var obj = objs[dragObj.idx];
  obj.alpha = 1;
  obj.scale.set(1);
  var pos = e.getLocalPosition(app.stage);
  var target = hitContainer(pos.x, pos.y);
  if (target >= 0) assign[dragObj.idx] = target;
  dragObj = null;
  for (var i = 0; i < N; i++) drawBox(cBgs[i], cRects[i], false);
  layoutAll();
}

app.stage.on('pointerup', endDrag);
app.stage.on('pointerupoutside', endDrag);

// --- Check Button ---
var checkBtn = new PIXI.Container();
var checkBg = new PIXI.Graphics();
checkBg.roundRect(-45, -16, 90, 32, 7);
checkBg.fill(0x6C63FF);
checkBtn.addChild(checkBg);
var checkTxt = new PIXI.Text({
  text: 'Check',
  style: { fontSize: 14, fill: 0xffffff, fontWeight: 'bold', fontFamily: 'Arial, sans-serif' }
});
checkTxt.anchor.set(0.5, 0.5);
checkBtn.addChild(checkTxt);
checkBtn.position.set(W / 2 - 55, H - FTR / 2);
checkBtn.eventMode = 'static';
checkBtn.cursor = 'pointer';
checkBtn.hitArea = new PIXI.Rectangle(-45, -16, 90, 32);
app.stage.addChild(checkBtn);

// --- Feedback ---
var feedEl = new PIXI.Text({
  text: '',
  style: { fontSize: 15, fill: 0x4ECDC4, fontWeight: 'bold', fontFamily: 'Arial, sans-serif' }
});
feedEl.anchor.set(0.5, 0.5);
feedEl.position.set(W / 2, H - 12);
app.stage.addChild(feedEl);

// --- Try Again Button (hidden) ---
var retryBtn = new PIXI.Container();
var retryBg = new PIXI.Graphics();
retryBg.roundRect(-48, -16, 96, 32, 7);
retryBg.fill(0x3a3a5a);
retryBtn.addChild(retryBg);
var retryTxt = new PIXI.Text({
  text: 'Try Again',
  style: { fontSize: 13, fill: 0xcccccc, fontFamily: 'Arial, sans-serif' }
});
retryTxt.anchor.set(0.5, 0.5);
retryBtn.addChild(retryTxt);
retryBtn.position.set(W / 2 + 55, H - FTR / 2);
retryBtn.eventMode = 'static';
retryBtn.cursor = 'pointer';
retryBtn.hitArea = new PIXI.Rectangle(-48, -16, 96, 32);
retryBtn.visible = false;
app.stage.addChild(retryBtn);

// --- Check Logic ---
checkBtn.on('pointertap', function() {
  if (isChecked) return;
  isChecked = true;

  // Count per container
  var counts = {};
  cDefs.forEach(function(d, i) {
    var n = 0;
    assign.forEach(function(a) { if (a === i) n++; });
    counts[d.label] = n;
  });

  // Evaluate goal
  var correct = true;
  var goalKeys = Object.keys(goal);
  for (var k = 0; k < goalKeys.length; k++) {
    if (counts[goalKeys[k]] !== goal[goalKeys[k]]) { correct = false; break; }
  }

  feedEl.text = correct ? successMsg : 'Not quite \u2014 try again!';
  feedEl.style.fill = correct ? 0x4ECDC4 : 0xFF6B6B;

  // Visual feedback
  for (var i = 0; i < N; i++) {
    var clr = correct ? 0x253a2a : null;
    if (!correct) {
      var ci_label = cDefs[i].label;
      if (goal[ci_label] !== undefined && counts[ci_label] !== goal[ci_label]) clr = 0x3a2525;
    }
    var r = cRects[i];
    cBgs[i].clear();
    cBgs[i].roundRect(r.x, r.y, r.w, r.h, 10);
    cBgs[i].fill(clr || 0x252545);
    cBgs[i].roundRect(r.x, r.y, r.w, r.h, 10);
    cBgs[i].stroke({
      width: 2,
      color: correct ? 0x4ECDC4 : (clr === 0x3a2525 ? 0xFF6B6B : 0x3a3a5a)
    });
  }

  // Disable drag
  objs.forEach(function(o) { o.eventMode = 'none'; o.cursor = 'default'; });

  // Dim check
  checkBg.clear();
  checkBg.roundRect(-45, -16, 90, 32, 7);
  checkBg.fill(0x3a3a5a);

  retryBtn.visible = true;

  // Notify parent
  try {
    window.parent.postMessage({
      type: 'interaction-complete',
      result: { correct: correct, counts: counts }
    }, '*');
  } catch (_) {}
});

// --- Retry Logic ---
retryBtn.on('pointertap', function() {
  isChecked = false;
  feedEl.text = '';
  retryBtn.visible = false;

  checkBg.clear();
  checkBg.roundRect(-45, -16, 90, 32, 7);
  checkBg.fill(0x6C63FF);

  resetAssignments();
  objs.forEach(function(o) { o.eventMode = 'static'; o.cursor = 'pointer'; });
  for (var i = 0; i < N; i++) drawBox(cBgs[i], cRects[i], false);
  layoutAll();
});
