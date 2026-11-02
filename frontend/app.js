const $=s=>document.querySelector(s),esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const ss=sessionStorage; // session storage: login page appears every time the app is opened fresh
const S={token:ss.getItem("pcs_token"),roll:ss.getItem("pcs_roll"),ds:null,page:"dashboard",filter:"all",q:"",sel:null};
const NAV=[["training","ML Training"],["performance","Model Performance"],["results","Screening Results"],["predict","Predict Cathode"],["export","Export Results"]];
const ic=p=>`<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const ICON={dashboard:ic('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>'),training:ic('<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>'),performance:ic('<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>'),results:ic('<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'),export:ic('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>')};
ICON.predict=ic('<path d="M9 3h6"/><path d="M10 3v6.5L4.5 19a1.5 1.5 0 0 0 1.3 2.2h12.4a1.5 1.5 0 0 0 1.3-2.2L14 9.5V3"/><path d="M7.5 15h9"/>');
const fmt=(v,d=3)=>v==null?"—":(typeof v==="number"?(Math.abs(v)<1e-3&&v!==0||Math.abs(v)>1e5?v.toExponential(2):+v.toFixed(d)):esc(v));
const badge=v=>`<span class="badge ${String(v).replace(/ /g,"")}">${v==="NOT AVAILABLE"?"N/A":v==="INCOMPLETE"?"NOT EVALUABLE":v}</span>`;
const toast=m=>{const t=$("#toast");t.textContent=m;t.style.display="block";setTimeout(()=>t.style.display="none",4000)};
async function api(p,o={}){o.headers={...(o.headers||{}),Authorization:"Bearer "+S.token};if(o.json){o.headers["Content-Type"]="application/json";o.body=JSON.stringify(o.json);o.method=o.method||"POST"}
 let r;try{r=await fetch("/api"+p,o)}catch(e){throw new Error("Cannot reach the server (API failure). Is the backend still running?")}
 if(r.status===401&&p!=="/login"){logout();throw new Error("Session expired – please log in again.")}
 if(!(r.headers.get("content-type")||"").includes("json"))return r;const j=await r.json();if(!r.ok)throw new Error(j.error||"Request failed");return j}
async function busy(msgs,fn){const b=$("#busy");b.classList.remove("hidden");let i=0;$("#busymsg").textContent=msgs[0];const t=setInterval(()=>$("#busymsg").textContent=msgs[Math.min(++i,msgs.length-1)],3000);
 try{return await fn()}finally{clearInterval(t);b.classList.add("hidden")}}
async function dl(path,name){await busy(["Preparing Excel..."],async()=>{const r=await api(path);if(r.blob){const u=URL.createObjectURL(await r.blob()),a=document.createElement("a");a.href=u;a.download=name;a.click()}})}
function logout(){ss.clear();S.token=null;S.ds=null;S.sel=null;show()}
$("#logout").onclick=logout;$("#mx").onclick=()=>$("#modal").classList.add("hidden");
$("#lf").onsubmit=async e=>{e.preventDefault();$("#lerr").textContent="";try{const j=await api("/login",{json:{roll_number:$("#roll").value,password:$("#pw").value}});S.token=j.token;S.roll=j.roll_number;ss.setItem("pcs_token",j.token);ss.setItem("pcs_roll",j.roll_number);$("#pw").value="";show()}catch(x){$("#lerr").textContent=x.message}};
async function show(){const ok=!!S.token;$("#login").classList.toggle("hidden",ok);$("#app").classList.toggle("hidden",!ok);if(!ok)return;$("#who").textContent="Roll No: "+S.roll;
 const id=ss.getItem("pcs_ds");if(id&&!S.ds){try{S.ds=await api("/datasets/"+id)}catch(e){ss.removeItem("pcs_ds")}}go(S.page||"dashboard")}
const backTo=()=>S.page==="results"||!S.ds||S.ds.status!=="screened"?"dashboard":"results";
function go(p){S.page=p;
 $("#nav").innerHTML=`<a class="${p==="dashboard"?"on":""}" onclick="go('dashboard')">${ICON.dashboard}Dashboard</a>`+(S.ds?`<div class="lbl">${esc(S.ds.filename)}</div>`+NAV.map(([k,l])=>`<a class="${k===p?"on":""}" onclick="go('${k}')">${ICON[k]||""}${l}</a>`).join(""):"");
 $("#bar").innerHTML=p==="dashboard"?"":`<button class="btn sec sm" onclick="go(backTo())">← Back</button><span class="muted small">${S.ds?esc(S.ds.filename):""}</span>`;
 $("#main").innerHTML="";window.scrollTo(0,0);Promise.resolve(P[p]()).catch(e=>{$("#main").innerHTML=`<div class="note bad">${esc(e.message)}</div>`})}
async function openDs(id,page){S.ds=await api("/datasets/"+id);ss.setItem("pcs_ds",id);S.filter="all";S.q="";S.sel=null;go(page||(S.ds.status==="screened"?"results":"training"))}
const need=()=>S.ds?"":`<div class="card">No dataset open. Go to the <a href="#" onclick="go('dashboard');return false">Dashboard</a> and click OPEN on a dataset.</div>`;
const stat=(v,l,c="")=>`<div class="stat ${c}"><b>${v}</b><span>${l}</span></div>`;
const P={};
P.dashboard=async()=>{const d=await api("/dashboard"),t=d.totals;
 const card=x=>`<div class="ds ${S.ds&&S.ds.id===x.id?"cur":""}"><div><b>${esc(x.filename)}</b><br><span class="muted small">${x.row_count} cathodes · Uploaded: ${x.upload_date} ${x.model?"· Model: "+x.model:""}</span><br>${x.status==="screened"?`PASS: <b>${x.pass}</b> &nbsp; FAIL: <b>${x.fail}</b>`:`<span class="badge NA">${x.status}</span> not screened yet`}</div>
 <div><button class="btn sm" onclick="openDs(${x.id})">OPEN</button> <button class="btn sm sec" ${x.status!=="screened"?"disabled":""} onclick="openDs(${x.id},'results')">RESULTS</button> <button class="btn sm sec" onclick="delDs(${x.id})">Delete</button></div></div>`;
 $("#main").innerHTML=`<h2>Welcome, ${esc(d.roll_number)}</h2><div class="grid g4">${stat(t.datasets,"Total datasets")}${stat(t.cathodes_screened,"Total cathodes screened")}${stat(t.pass,"Total PASS","p")}${stat(t.fail,"Total FAIL","f")}</div><p class="small muted">Totals count each distinct formula once, even if it appears in several rows or datasets.</p>
 <div class="drop" id="dz" style="padding:22px"><b style="font-size:16px">Upload New Dataset</b><br><span class="muted">Drop a CSV / Excel file here or click to browse (.csv .xlsx .xls) — one row per cathode</span><input type="file" id="fi" accept=".csv,.xlsx,.xls" class="hidden"></div>
 <h3 style="margin-top:18px">MY RECENT SCREENINGS</h3>${d.datasets.map(card).join("")||'<p class="muted">No datasets uploaded yet.</p>'}`;
 const dz=$("#dz"),fi=$("#fi");dz.onclick=()=>fi.click();dz.ondragover=e=>{e.preventDefault();dz.classList.add("over")};dz.ondragleave=()=>dz.classList.remove("over");dz.ondrop=e=>{e.preventDefault();dz.classList.remove("over");up(e.dataTransfer.files[0])};fi.onchange=()=>up(fi.files[0])};
window.delDs=async id=>{if(confirm("Delete this dataset and all its results?")){await api("/datasets/"+id,{method:"DELETE"});if(S.ds&&S.ds.id===id){S.ds=null;ss.removeItem("pcs_ds")}go("dashboard")}};
async function up(f){if(!f)return;const fd=new FormData();fd.append("file",f);try{const j=await busy(["Uploading dataset...","Analyzing dataset..."],()=>api("/datasets",{method:"POST",body:fd}));if(j.duplicate)toast("This dataset is already in your history – opened the existing copy.");await openDs(j.id)}catch(e){toast(e.message)}}
const selc=(id,cols,val)=>`<select id="${id}"><option value="">— choose column —</option>${cols.map(c=>`<option ${c===val?"selected":""}>${esc(c)}</option>`).join("")}</select>`;
const NA='<span class="na">Not available</span>';
P.training=()=>{if(!S.ds)return $("#main").innerHTML=need();const a=S.ds.analysis,m=S.ds.train?.mapping||a.mapping,t=S.ds.train,miss=Object.entries(a.missing),inv=Object.entries(a.invalid_numeric),d=a.descriptors;
 const row=(l,col,id)=>`<tr><td>${l}</td><td>${col?`<b>${esc(col)}</b>`:(id?selc(id,a.columns,null)+' <span class="na">Not available – choose it</span>':NA)}</td></tr>`;
 $("#main").innerHTML=`<h2>ML Training &amp; Dataset Analysis</h2><div class="grid g4">${stat(esc(S.ds.filename).slice(0,22),"File")}${stat(a.rows,"Cathodes (rows)")}${stat(a.n_columns,"Columns")}${stat(a.duplicates_removed,"Duplicate rows removed")}${stat(miss.reduce((s,x)=>s+x[1],0),"Missing values")}</div>
 ${a.target_note?`<div class="note">${esc(a.target_note)}</div>`:""}${!m.ehull?'<div class="note bad">Ehull column is <b>not available</b> in this dataset – the Ehull criterion cannot be evaluated, so no cathode can receive a full PASS.</div>':""}
 <div class="card"><h3>Detected column mapping</h3><table>${row("Chemical formula",m.formula,"m_f")}${row("Target log10(k*)",m.target,"m_t")}${row("Ehull (screening only)",m.ehull)}${row("Temperature / 1000/T",m.temperature)}</table></div>
 <div class="card"><h3>Paper descriptors vs. your dataset</h3><p class="small muted">Descriptors missing from the dataset are left out – nothing is invented. Enhanced descriptors are only used by the interpretation model, never for screening.</p>
 <div class="tw"><table><thead><tr><th>Paper descriptor</th><th>Group</th><th>Dataset column</th><th>Status</th></tr></thead><tbody>${d.map(e=>`<tr><td>${esc(e.label)}</td><td>${e.group}</td><td>${e.column?esc(e.column):"—"}</td><td>${e.usable?'<span class="ok">Available</span>':`<span class="na">Not available</span> <span class="small muted">${e.present?"("+esc(e.reason)+")":""}</span>`}</td></tr>`).join("")}</tbody></table></div></div>
 ${miss.length?`<div class="card"><h3>Missing values</h3>${miss.map(([c,n])=>`${esc(c)}: ${n}`).join(" · ")}<p class="small muted">Filled with the training-fold median inside the Pipeline (no leakage).</p></div>`:""}
 ${inv.length?`<div class="card"><h3>Invalid numerical values</h3>${inv.map(([c,n])=>`${esc(c)}: ${n} non-numeric entries treated as missing`).join("<br>")}</div>`:""}
 <div class="card"><h3>Training</h3><p>Data is split <b>60 : 40 grouped by composition</b> (a composition is never in both parts). On the training part: redundant descriptors (|r| &gt; 0.95) are removed, then <b>backward feature elimination</b> with grouped 5-fold CV (RMSE) picks the smallest feature set within 1 standard error (1000/T always kept). Imputer → StandardScaler → model sit in one Pipeline (re-fitted in every fold). MLP, SVR, GBR, KNN, RF are compared on the unseen 40% · <b>SVR is the primary model</b> · Mahalanobis applicability domain · screening. <b>The model, screening and predictions use only the selected features</b>, and the trained model is saved automatically for the <b>Predict Cathode</b> tab.</p>
 ${t?`<div class="note ok"><b>Selected features (${t.features.length}${t.feature_selection?" of "+t.feature_selection.n_candidates:""}):</b> ${t.features.map(c=>`<span class="pill">${esc(c)}</span>`).join("")}<br><span class="small">Grouped split: ${t.n_train} rows (${t.n_train_groups??"–"} compositions) trained · ${t.n_test} rows (${t.n_test_groups??"–"} compositions) tested. ${t.feature_selection&&t.feature_selection.dropped_redundant.length?`Dropped as redundant: ${t.feature_selection.dropped_redundant.map(x=>esc(x.dropped)).join(", ")}. `:""}Model saved. Open <b>Model Performance</b> for the full feature-selection report.</span></div>`:'<div class="note">Not trained yet.</div>'}
 <button class="btn" onclick="runAll()">${t?"Re-train &amp; re-screen":"Train models &amp; screen all cathodes"}</button> <span class="small muted">usually under a minute or two</span></div>`};
window.runAll=async()=>{const a=S.ds.analysis,v=id=>$("#"+id)?.value||null;const mp={formula:v("m_f"),target:v("m_t")};
 try{await busy(["Preparing features...","Training models...","Validating models..."],()=>api(`/datasets/${S.ds.id}/train`,{json:{mapping:mp}}));
 await busy(["Predicting cathodes...","Applying screening criteria...","Generating results..."],()=>api(`/datasets/${S.ds.id}/screen`,{method:"POST"}));await openDs(S.ds.id,"results")}catch(e){toast(e.message);go("training");$("#main").insertAdjacentHTML("afterbegin",`<div class="note bad">${esc(e.message)}</div>`)}};
const absbars=items=>{const mx=Math.max(...items.map(x=>x.mean_abs),1e-9);return items.map(x=>`<div class="hb"><div class="l" title="${esc(x.label)}">${esc(x.feature)}</div><div class="t"><div class="v" style="left:0;width:${100*x.mean_abs/mx}%;background:${x.corr_with_value>0.1?"var(--pass)":x.corr_with_value<-0.1?"var(--fail)":"var(--mut)"}"></div></div><span style="width:50px">${fmt(x.mean_abs,2)}</span></div>`).join("")};
function parity(p){
 const W=380,pad=40,all=p.y.concat(p.pred,p.y_train||[],p.pred_train||[]),lo=Math.min(...all),hi=Math.max(...all),sc=v=>pad+(v-lo)/(hi-lo)*(W-2*pad),tk=[0,1,2,3,4].map(i=>lo+(hi-lo)*i/4);
 const grid=tk.map(v=>`<line x1="${sc(v)}" x2="${sc(v)}" y1="${pad-10}" y2="${W-pad}" stroke="#eef2f6"/><line y1="${W-sc(v)}" y2="${W-sc(v)}" x1="${pad}" x2="${W-pad+10}" stroke="#eef2f6"/><text x="${sc(v)}" y="${W-pad+16}" text-anchor="middle" font-size="10" fill="#64748b">${v.toFixed(1)}</text><text x="${pad-6}" y="${W-sc(v)+3}" text-anchor="end" font-size="10" fill="#64748b">${v.toFixed(1)}</text>`).join("");
 const dots=(ys,ps,c,o,r)=>(ys||[]).map((y,i)=>`<circle cx="${sc(y)}" cy="${W-sc(ps[i])}" r="${r}" fill="${c}" opacity="${o}"/>`).join("");
 return `<svg viewBox="0 0 ${W} ${W}" style="width:100%;max-width:${W}px;background:#fff;border:1px solid var(--line);border-radius:10px">${grid}<line x1="${sc(lo)}" y1="${W-sc(lo)}" x2="${sc(hi)}" y2="${W-sc(hi)}" stroke="#c1121f" stroke-dasharray="5 4"/>${dots(p.y_train,p.pred_train,"#9db4c4",.55,3)}${dots(p.y,p.pred,"#0f8b8d",.9,4.5)}<text x="${W/2}" y="${W-6}" text-anchor="middle" font-size="11" fill="#0f2a43">experimental log10(k*)</text><text x="11" y="${W/2}" font-size="11" fill="#0f2a43" transform="rotate(-90 11 ${W/2})" text-anchor="middle">predicted log10(k*)</text></svg>
 <div class="lg"><span><i style="background:#0f8b8d"></i>Test set (40%, unseen)</span><span><i style="background:#9db4c4"></i>Training set (60%)</span><span>Dashed line = perfect prediction</span></div>`}

// ---------- correlation & covariance ----------
const relNum=v=>v==null?"—":(Math.abs(v)>=100?v.toFixed(0):Math.abs(v)>=10?v.toFixed(1):v.toFixed(2));
const REL_TXT={corr:"<b>Correlation (Pearson r)</b> shows how strongly two variables move together, from −1 to +1. <b style='color:#2563eb'>Blue (+)</b> = they rise together, <b style='color:#dc2626'>red (−)</b> = one rises while the other falls, white = no linear relation. It does not depend on units.",
 cov:"<b>Covariance</b> shows how two variables vary together in their original units, so its size depends on each variable’s scale – compare the <b>signs</b> (blue = positive, red = negative) rather than the sizes. The grey diagonal is each variable’s variance. Colour strength is relative to the largest off-diagonal value."};
function relMatrix(st,mode){
 const M=mode==="corr"?st.corr:st.cov,nm=st.names,n=nm.length;let mx=1;
 if(mode==="cov"){mx=0;M.forEach((r,i)=>r.forEach((v,j)=>{if(i!==j&&v!=null)mx=Math.max(mx,Math.abs(v))}));mx=mx||1}
 const cell=(v,i,j)=>{if(v==null)return '<td class="mx-n">—</td>';const a=Math.min(1,Math.abs(v)/mx),
   bg=i===j?"rgba(100,116,139,.16)":(v>=0?`rgba(37,99,235,${(.08+.82*a).toFixed(2)})`:`rgba(220,38,38,${(.08+.82*a).toFixed(2)})`);
  return `<td style="background:${bg};color:${i!==j&&a>.55?"#fff":"#0f2a43"}" title="${esc(nm[i])} × ${esc(nm[j])}: ${v}">${mode==="corr"?v.toFixed(2):relNum(v)}</td>`};
 return `<div class="mx-wrap"><table class="mx"><thead><tr><th></th>${nm.map((c,j)=>`<th class="${j===n-1?"mx-t":""}"><span>${esc(c)}</span></th>`).join("")}</tr></thead><tbody>${M.map((row,i)=>`<tr><th class="mx-r ${i===n-1?"mx-t":""}">${esc(nm[i])}</th>${row.map((v,j)=>cell(v,i,j)).join("")}</tr>`).join("")}</tbody></table></div>`}
window.setRel=m=>{const st=S.ds.train.stats;$("#relbox").innerHTML=relMatrix(st,m);$("#rel_txt").innerHTML=REL_TXT[m];["corr","cov"].forEach(k=>$("#rt_"+k).classList.toggle("on",k===m))};
function relCard(t){
 const st=t.stats;
 if(!st)return '<div class="card"><h3>Correlation &amp; covariance</h3><div class="note">Click <b>Re-train &amp; re-screen</b> on the ML Training page once to see the correlation and covariance matrices.</div></div>';
 const ti=st.names.length-1,rel=st.names.slice(0,ti).map((c,i)=>({c,r:st.corr[i][ti]})).filter(x=>x.r!=null).sort((a,b)=>Math.abs(b.r)-Math.abs(a.r)),pairs=[];
 for(let i=0;i<ti;i++)for(let j=i+1;j<ti;j++){const r=st.corr[i][j];if(r!=null&&Math.abs(r)>=0.8)pairs.push({a:st.names[i],b:st.names[j],r})}
 pairs.sort((x,y)=>Math.abs(y.r)-Math.abs(x.r));
 const word=r=>{const a=Math.abs(r);return a>=.8?"very strong":a>=.6?"strong":a>=.4?"moderate":a>=.2?"weak":"very weak"};
 return `<div class="card"><div class="card-h"><div><h3>Correlation &amp; covariance</h3><p>Calculated on the ${st.n} training cathodes: ${ti} descriptors plus the target <b>${esc(st.target)}</b> (last row and column).</p></div><div class="rtabs"><button class="rtab on" id="rt_corr" onclick="setRel('corr')">Correlation</button><button class="rtab" id="rt_cov" onclick="setRel('cov')">Covariance</button></div></div>
  <p class="small" id="rel_txt">${REL_TXT.corr}</p><div id="relbox">${relMatrix(st,"corr")}</div>
  <div class="grid g2" style="margin-top:18px"><div><h4>How each descriptor relates to ${esc(st.target)}</h4>${rel.map(x=>`<div class="rrow"><span class="rn">${esc(x.c)}</span><div class="rt"><i class="mid"></i><div class="rv" style="${x.r>=0?"left":"right"}:50%;width:${Math.abs(x.r)*50}%;background:${x.r>=0?"#2563eb":"#dc2626"}"></div></div><span class="rr"><b>${x.r.toFixed(2)}</b> <span class="muted">${word(x.r)}</span></span></div>`).join("")}</div>
  <div><h4>Strongly related descriptor pairs (|r| ≥ 0.80)</h4>${pairs.length?`<div class="tw"><table><thead><tr><th>Descriptor A</th><th>Descriptor B</th><th>r</th></tr></thead><tbody>${pairs.slice(0,10).map(p=>`<tr><td>${esc(p.a)}</td><td>${esc(p.b)}</td><td><b style="color:${p.r>0?"#2563eb":"#dc2626"}">${p.r.toFixed(2)}</b></td></tr>`).join("")}</tbody></table></div><p class="small muted">Such pairs carry almost the same information.</p>`:'<p class="small muted">No pair of descriptors is correlated above 0.80.</p>'}</div></div></div>`}

// ---------- NEW: feature-selection report (Model Performance page) ----------
const pills=a=>a.map(c=>`<span class="pill">${esc(c)}</span>`).join("");
function rmsePlot(fs){
 const H=fs.history,W=640,Hh=330,L=62,R=22,T=22,B=52,xs=H.map(h=>h.n_features),mn=Math.min(...xs),mx=Math.max(...xs);
 const lo=Math.min(...H.map(h=>h.cv_rmse-h.cv_rmse_se)),hi=Math.max(...H.map(h=>h.cv_rmse+h.cv_rmse_se),fs.rmse_limit),pad=(hi-lo)*.08||.1,y0=Math.max(0,lo-pad),y1=hi+pad;
 const px=v=>L+(mx===mn?.5:(v-mn)/(mx-mn))*(W-L-R),py=v=>Hh-B-(v-y0)/(y1-y0)*(Hh-B-T);
 const yt=[0,1,2,3,4].map(i=>y0+(y1-y0)*i/4),pts=[...H].sort((a,b)=>a.n_features-b.n_features);
 const sel=H.find(h=>h.n_features===fs.selected_n)||H[H.length-1],best=H.find(h=>h.n_features===fs.min_n_features)||H[0];
 return `<svg viewBox="0 0 ${W} ${Hh}" class="sc" role="img" aria-label="CV RMSE versus number of features">
  ${yt.map(v=>`<line x1="${L}" x2="${W-R}" y1="${py(v)}" y2="${py(v)}" stroke="#eaeff4"/><text x="${L-8}" y="${py(v)+4}" text-anchor="end" font-size="11" fill="#64748b">${v.toFixed(2)}</text>`).join("")}
  ${pts.map(h=>`<text x="${px(h.n_features)}" y="${Hh-B+18}" text-anchor="middle" font-size="11" fill="#64748b">${h.n_features}</text>`).join("")}
  <line x1="${L}" x2="${W-R}" y1="${py(fs.rmse_limit)}" y2="${py(fs.rmse_limit)}" stroke="#c58b00" stroke-dasharray="6 5" stroke-width="1.6"/><text x="${W-R-4}" y="${py(fs.rmse_limit)-6}" text-anchor="end" font-size="11" fill="#8a6500" font-weight="700">1-SE limit = ${fs.rmse_limit.toFixed(3)}</text>
  <polyline fill="none" stroke="#0f8b8d" stroke-width="2" points="${pts.map(h=>`${px(h.n_features)},${py(h.cv_rmse)}`).join(" ")}"/>
  ${pts.map(h=>`<line x1="${px(h.n_features)}" x2="${px(h.n_features)}" y1="${py(h.cv_rmse-h.cv_rmse_se)}" y2="${py(h.cv_rmse+h.cv_rmse_se)}" stroke="#7fb9ba" stroke-width="1.5"/><circle cx="${px(h.n_features)}" cy="${py(h.cv_rmse)}" r="4" fill="#0f8b8d"><title>${h.n_features} features${h.removed?` (removed ${h.removed})`:""}\nCV RMSE ${h.cv_rmse.toFixed(3)} ± ${h.cv_rmse_se.toFixed(3)}\nCV R² ${h.cv_r2.toFixed(3)}</title></circle>`).join("")}
  <circle cx="${px(best.n_features)}" cy="${py(best.cv_rmse)}" r="8" fill="none" stroke="#1ea84a" stroke-width="2.4"/><text x="${px(best.n_features)}" y="${py(best.cv_rmse)+22}" text-anchor="middle" font-size="11" fill="#13762f" font-weight="700">lowest RMSE</text>
  <circle cx="${px(sel.n_features)}" cy="${py(sel.cv_rmse)}" r="9" fill="none" stroke="#0f2a43" stroke-width="2.6"/><text x="${px(sel.n_features)}" y="${py(sel.cv_rmse)-14}" text-anchor="middle" font-size="12" fill="#0f2a43" font-weight="800">selected (${sel.n_features})</text>
  <line x1="${L}" x2="${W-R}" y1="${Hh-B}" y2="${Hh-B}" stroke="#94a3b8"/><line x1="${L}" x2="${L}" y1="${T}" y2="${Hh-B}" stroke="#94a3b8"/>
  <text x="${(L+W-R)/2}" y="${Hh-10}" text-anchor="middle" font-size="12.5" font-weight="600" fill="#0f2a43">Number of features</text>
  <text transform="translate(16 ${(T+Hh-B)/2}) rotate(-90)" text-anchor="middle" font-size="12.5" font-weight="600" fill="#0f2a43">Grouped 5-fold CV RMSE (log10 k*)</text></svg>`}
function permBars(list){
 const mx=Math.max(...list.map(x=>x.importance+x.std),1e-9);
 return list.map(x=>`<div class="prow"><span class="pn">${esc(x.feature)}</span><div class="pt"><div class="pv2" style="width:${Math.max(0,x.importance)/mx*100}%"></div><i class="pe" style="left:${Math.max(0,x.importance-x.std)/mx*100}%;width:${(Math.min(x.importance+x.std,mx)-Math.max(0,x.importance-x.std))/mx*100}%"></i></div><span class="pr"><b>${x.importance.toFixed(3)}</b> <span class="muted">± ${x.std.toFixed(3)}</span></span></div>`).join("")}
function fsReport(t){
 const fs=t.feature_selection;
 if(!fs)return '<div class="card"><h3>Feature selection</h3><div class="note">Click <b>Re-train &amp; re-screen</b> on the ML Training page once to run the feature selection.</div></div>';
 const v=fs.versus,o=v.original,n=v.selected,d=(a,b,f=3)=>{const x=b-a;return (x>0?"+":"")+x.toFixed(f)};
 const removed=fs.history.filter(h=>h.removed).map(h=>h.removed),elim=removed.filter(c=>!fs.selected.includes(c));
 return `<div class="card sel-card"><div class="card-h"><div><h3>Selected features – the model uses only these ${fs.selected.length}</h3><p>Chosen from ${fs.n_candidates} candidate descriptors using the training part only (grouped by composition, so no composition is ever in two parts).</p></div></div>
  <div class="selpills">${pills(fs.selected)}</div>
  <ul class="fs-steps"><li><b>Non-numeric columns ignored:</b> ${fs.non_numeric_dropped.length?esc(fs.non_numeric_dropped.join(", ")):"none"} (the target is log10(k*)).</li>
   <li><b>Redundant descriptors dropped (|r| &gt; 0.95):</b> ${fs.dropped_redundant.length?esc(fs.dropped_redundant.map(x=>x.dropped).join(", ")):"none"}.</li>
   <li><b>Removed by backward elimination:</b> ${elim.length?esc(elim.join(", ")):"none"}.</li>
   <li><b>Always kept:</b> ${fs.keep_always.length?esc(fs.keep_always.join(", ")):"–"}.</li></ul></div>
 <div class="card"><h3>Original model vs new model</h3><p class="small muted">Same SVR, same grouped split. “Original” uses all ${o.n_features} descriptors; “New” uses only the ${n.n_features} selected ones. The test set was never used for the selection, so the test columns are the fair comparison (the CV columns are slightly optimistic for the new model because the features were chosen on those folds).</p>
  <div class="tw"><table><thead><tr><th>Model</th><th>Features</th><th>Grouped-CV R²</th><th>Grouped-CV RMSE</th><th>Test R²</th><th>Test RMSE</th></tr></thead><tbody>
   <tr><td><b>${o.label}</b></td><td>${o.n_features}</td><td>${o.cv_r2.toFixed(3)}</td><td>${o.cv_rmse.toFixed(3)}</td><td>${o.test_r2.toFixed(3)}</td><td>${o.test_rmse.toFixed(3)}</td></tr>
   <tr class="sel-row"><td><b>${n.label}</b></td><td>${n.n_features}</td><td>${n.cv_r2.toFixed(3)}</td><td>${n.cv_rmse.toFixed(3)}</td><td><b>${n.test_r2.toFixed(3)}</b></td><td><b>${n.test_rmse.toFixed(3)}</b></td></tr>
   <tr><td class="muted">Change (new − original)</td><td class="muted">${n.n_features-o.n_features}</td><td class="muted">${d(o.cv_r2,n.cv_r2)}</td><td class="muted">${d(o.cv_rmse,n.cv_rmse)}</td><td class="muted">${d(o.test_r2,n.test_r2)}</td><td class="muted">${d(o.test_rmse,n.test_rmse)}</td></tr></tbody></table></div></div>
 <div class="card"><div class="card-h"><div><h3>Backward feature elimination</h3><p>At every step the feature whose removal gives the lowest grouped-CV RMSE is removed (scaler fitted inside each fold). The smallest feature set whose RMSE is within one standard error of the lowest RMSE is selected. ${fs.elimination_rows<(t.n_train||0)?`Elimination ran on ${fs.elimination_rows} rows (whole compositions) to stay fast.`:""}</p></div></div>
  <div class="rmse-wrap">${rmsePlot(fs)}</div>
  <div class="tw" style="margin-top:14px"><table><thead><tr><th>Features left</th><th>Removed feature</th><th>CV R²</th><th>CV RMSE</th><th>± SE</th></tr></thead><tbody>${fs.history.map(h=>`<tr class="${h.n_features===fs.selected_n?"sel-row":""}"><td><b>${h.n_features}</b>${h.n_features===fs.selected_n?' <span class="badge PASS">selected</span>':""}</td><td>${h.removed?esc(h.removed):'<span class="muted">– (all descriptors after redundancy removal)</span>'}</td><td>${h.cv_r2.toFixed(3)}</td><td>${h.cv_rmse.toFixed(3)}</td><td class="muted">${h.cv_rmse_se.toFixed(3)}</td></tr>`).join("")}</tbody></table></div></div>
 <div class="grid g2"><div class="card"><h3>Redundant descriptors removed</h3><p class="small muted">Pairs with |Pearson r| &gt; 0.95: the one with the lower |Spearman| correlation to log10(k*) is dropped.</p>${fs.dropped_redundant.length?`<div class="tw"><table><thead><tr><th>Dropped</th><th>Kept</th><th>|r|</th><th>Spearman (dropped / kept)</th></tr></thead><tbody>${fs.dropped_redundant.map(x=>`<tr><td><b>${esc(x.dropped)}</b></td><td>${esc(x.kept)}</td><td>${x.r.toFixed(3)}</td><td>${x.spearman_dropped.toFixed(3)} / ${x.spearman_kept.toFixed(3)}</td></tr>`).join("")}</tbody></table></div>`:'<div class="note ok">No pair of descriptors had |r| &gt; 0.95, so nothing was dropped as redundant.</div>'}</div>
  <div class="card"><h3>Permutation importance</h3><p class="small muted">Increase in RMSE when a feature is shuffled (${fs.perm_repeats} repeats, on the held-out folds of the final set, averaged over folds). Longer bar = more important.</p>${permBars(fs.permutation)}</div></div>`}

P.performance=()=>{if(!S.ds)return $("#main").innerHTML=need();const t=S.ds.train;if(!t)return $("#main").innerHTML='<div class="note">Train the models first (ML Training page).</div>';
 if(t.n_test==null||t.n_groups==null)return $("#main").innerHTML='<div class="note">This dataset was trained with an older version (no grouped split / feature selection). Open ML Training and click <b>Re-train &amp; re-screen</b> to update it.</div>';
 const best=t.best_by_test_r2,svr=t.comparison.find(m=>m.model==="SVR")||{};
 $("#main").innerHTML=`<h2>Model Performance</h2>
 <div class="grid g4">${stat(t.n_total,"Rows with a target")}${stat(t.n_groups,"Distinct compositions")}${stat(t.n_train+" / "+t.n_test,"Train / test rows (60:40 by composition)")}${stat(fmt(svr.R2,3),"SVR test R²","p")}</div>
 <div style="margin-top:16px">${fsReport(t)}</div>
 <div class="card"><h3>Model comparison on the selected features – scores on the unseen 40% testing set</h3><div class="tw"><table><thead><tr><th>Model</th><th>Test R²</th><th>Test MAE</th><th>Test RMSE</th><th>Train R²</th><th>Grouped-CV R² (train part)</th><th>Tuning</th><th>Best params</th></tr></thead><tbody>${t.comparison.map(m=>`<tr><td><b>${m.model}</b> ${m.model==="SVR"?'<span class="badge PASS">primary</span>':""}</td><td><b>${fmt(m.R2)}</b></td><td>${fmt(m.MAE)}</td><td>${fmt(m.RMSE)}</td><td>${fmt(m.train_R2)}</td><td>${fmt(m.cv_R2)} ± ${fmt(m.cv_R2_std,2)}</td><td class="small">${esc(m.search)}</td><td class="small">${esc(JSON.stringify(m.params))}</td></tr>`).join("")}</tbody></table></div>
 <p class="small muted">${esc(t.cv)} SVR is the primary model as in the paper${best!=="SVR"?` (on this dataset ${best} has the highest test R²)`:" (it also has the highest test R² here)"}. Paper values (larger dataset): SVR R²=0.853, MAE=0.365.</p></div>
 <div class="grid g2"><div class="card"><h3>SVR: predicted vs experimental</h3>${parity(t.parity)}</div><div class="card"><h3>Applicability domain</h3><p>Mahalanobis distance in scaled feature space (selected features); threshold = ${t.ad.quantile} quantile of the ${t.ad.n_train} training distances = <b>${fmt(t.ad.threshold,2)}</b>.</p><p class="small muted">About ${Math.round((1-t.ad.quantile)*100)}% of training rows fall outside by construction.</p><h3>Features used by the model</h3><p class="small">${t.features.map(esc).join(", ")}</p>${t.unavailable_descriptors.length?`<p class="small"><b>Not available in the dataset:</b> <span class="na">${t.unavailable_descriptors.map(u=>esc(u.key)).join(", ")}</span></p>`:""}</div></div>
 ${relCard(t)}`};
const CR=(l,p,f,n,T)=>`<div><b>${l}</b> <span class="small muted">pass ${p} · fail ${f}${n?` · N/A ${n}`:""}</span><div class="bar"><i style="width:${100*p/T}%;background:var(--pass)"></i><i style="width:${100*f/T}%;background:var(--fail)"></i><i style="width:${100*n/T}%;background:var(--na)"></i></div></div>`;
// ---- Screening Results tab ----
const SC={PASS:"#1ea84a",FAIL:"#c1121f",INCOMPLETE:"#c58b00"};
const TC={green:"#1ea84a",orange:"#ff8a00",red:"#a50e1a"};

// ---------- Criteria card ----------
function critCard(title,limit,p,f,n){
  const tot=p+f+n,ev=p+f;
  if(!ev)return `<div class="crit"><div class="crit-t">${title}</div><div class="crit-l">${limit}</div><div class="crit-na">Not available</div><div class="small muted">This criterion could not be evaluated for this dataset.</div></div>`;
  const pct=Math.round(p/ev*100),w=v=>(100*v/tot).toFixed(2)+"%";
  return `<div class="crit"><div class="crit-t">${title}</div><div class="crit-l">${limit}</div>
   <div class="crit-v">${pct}<small>%</small><em>PASS RATE</em></div>
   <div class="seg"><i style="width:${w(p)};background:var(--green)"></i><i style="width:${w(f)};background:var(--red)"></i>${n?`<i style="width:${w(n)};background:var(--amber)"></i>`:""}</div>
   <div class="crit-n"><span><i class="d g"></i><b>${p}</b> pass</span><span><i class="d r"></i><b>${f}</b> fail</span>${n?`<span><i class="d a"></i><b>${n}</b> N/A</span>`:""}</div></div>`;
}

// ---------- log10(k*) card ----------
async function lk(){
  const el=$("#lkcard");if(!el)return;
  const r=await api(`/datasets/${S.ds.id}/results?filter=all&q=`),v=r.map(x=>x.predicted_log_kstar).filter(x=>x!=null).sort((a,b)=>a-b);
  if(!v.length){el.innerHTML='<div class="crit-t">Predicted log10(k*)</div><div class="crit-na">No data</div>';return}
  const n=v.length,mx=v[n-1],above=v.filter(t=>t>=-6.4).length,below=n-above,w=c=>(100*c/n).toFixed(2)+"%";
  el.innerHTML=`<div class="crit-t">Predicted log10(k*)</div><div class="crit-l">Surface exchange coefficient, log scale</div>
   <div class="crit-v">${fmt(mx,2)}<em>HIGHEST</em></div>
   <div class="seg"><i style="width:${w(above)};background:var(--green)"></i><i style="width:${w(below)};background:var(--red)"></i></div>
   <div class="crit-n"><span><i class="d g"></i><b>${above}</b> ≥ −6.40</span><span><i class="d r"></i><b>${below}</b> below</span></div>`;
}

// ---------- Rankings list ----------


P.results=async()=>{
  S.filter="all";
  if(!S.ds)return $("#main").innerHTML=need();
  const s=S.ds.summary;
  if(!s)return $("#main").innerHTML='<div class="note">Not screened yet – open <a href="#" onclick="go(\'training\');return false">ML Training</a> and run it.</div>';
  $("#main").innerHTML=`<div class="ph"><div><h2>Screening Results</h2><div class="sub">${esc(S.ds.filename)} · ${s.total} cathodes screened</div></div><button class="btn sec" onclick="go('export')">Export results</button></div>
   <div class="grid g4">${stat(s.total,"Total cathodes")}${stat(s.PASS,"PASS","p")}${stat(s.FAIL,"FAIL","f")}${s.INCOMPLETE?stat(s.INCOMPLETE,"Not evaluable","n"):""}${stat(s.pass_pct+"%","Pass rate")}</div>
   ${s.duplicates_merged?`<p class="small muted">${s.duplicates_merged} rows with a repeated formula were merged – each formula is counted once.</p>`:""}
   ${!s.ehull_available?'<div class="note bad">Ehull is <span class="na">not available</span> in this dataset, so the Ehull criterion could not be evaluated.</div>':""}
   <div class="sec-t">Screening criteria</div>
   <div class="grid g4c">${critCard("Applicability domain","Mahalanobis distance inside the training domain",s.inside_ad,s.outside_ad,0)}${critCard("Stability: Ehull","Pass if Ehull ≤ 57 meV/atom",s.ehull_pass,s.ehull_fail,s.ehull_not_available)}${critCard("ORR activity","Pass if predicted log10(k*) ≥ −6.40 (LSC benchmark)",s.orr_pass,s.orr_fail,0)}<div class="crit" id="lkcard"><div class="crit-t">Predicted log10(k*)</div><div class="crit-l">Surface exchange coefficient, log scale</div><p class="small muted">Loading…</p></div></div>
   <div class="sec-t">Cathode ranking</div>
   <div class="card flush">
        <div class="tool"><input id="q" placeholder="Search formula…" value="${esc(S.q)}"></div>
    <div class="tw"><table><thead><tr><th>Rank</th><th>Cathode / Formula</th><th>Final</th></tr></thead><tbody id="tb"></tbody></table></div>
    <p class="small muted" id="cnt" style="padding:10px 20px;margin:0"></p>
   </div>
   <p class="small muted">Click a cathode name to see its full details and ML training information. Final decision follows the paper’s sequence (applicability domain → Ehull → ORR); any failure = FAIL.</p>`;
  let tm;$("#q").oninput=e=>{S.q=e.target.value;clearTimeout(tm);tm=setTimeout(loadRes,250)};
  loadRes();lk().catch(()=>{});
};
async function loadRes(){
  const r=await api(`/datasets/${S.ds.id}/results?filter=${S.filter}&q=${encodeURIComponent(S.q)}`);
  document.querySelectorAll(".chip").forEach(c=>c.classList.toggle("on",c.dataset.k===S.filter));
  $("#tb").innerHTML=r.map(x=>`<tr class="click t-${x.tier}" onclick="detail(${x.id})"><td><b>#${x.rank}</b></td><td><a class="flink">${esc(x.formula)}</a></td><td>${badge(x.final_result)}</td></tr>`).join("");
  $("#cnt").textContent=r.length+" cathodes shown · click a name for details";
}

const dhtml=x=>{
 const d=x.detail,t=d.thresholds,f=x.final_result,p=x.orr_value,e=x.ehull,k=x.predicted_kstar,
  orrM=p-t.orr,ehM=e==null?null:t.ehull-e,adR=x.mahalanobis_distance/t.ad,dist=fmt(x.mahalanobis_distance,2),fails=[];
 if(x.ad_result==="FAIL")fails.push(`It lies <b>outside the applicability domain</b> – its distance of ${dist} is above the limit of ${fmt(t.ad,2)}, so the model’s prediction for it is less reliable.`);
 if(x.ehull_result==="FAIL")fails.push(`Its <b>Ehull</b> of ${fmt(e,1)} meV/atom is ${fmt(-ehM,1)} above the ${t.ehull} meV/atom limit, so it is not stable enough.`);
 if(x.orr_result==="FAIL")fails.push(`Its predicted <b>log10(k*)</b> of ${fmt(p,2)} is ${fmt(-orrM,2)} below the ${t.orr} benchmark, so it is not active enough.`);
 const expl=f==="PASS"
  ?`<div class="expl good"><b>${esc(x.formula)}</b> passes every screening check.<ul><li>Applicability domain: inside – distance ${dist} is within the limit of ${fmt(t.ad,2)}.</li><li>Stability: Ehull of ${fmt(e,1)} meV/atom is within the ${t.ehull} limit (${fmt(ehM,1)} below it).</li><li>Activity: predicted log10(k*) of ${fmt(p,2)} is ${fmt(orrM,2)} above the ${t.orr} benchmark.</li></ul></div>`
  :f==="FAIL"
  ?`<div class="expl bad"><b>${esc(x.formula)}</b> failed screening. <b>Why it failed:</b><ul>${fails.map(m=>`<li>${m}</li>`).join("")}</ul></div>`
  :`<div class="expl"><b>${esc(x.formula)}</b> could not be fully evaluated. ${d.not_available.map(esc).join(" ")}${fails.length?`<ul>${fails.map(m=>`<li>${m}</li>`).join("")}</ul>`:""}</div>`;
 const chk=(ti,res,val,req,margin,pct)=>`<div class="chk ${String(res).replace(/ /g,"")}"><div class="t"><span>${ti}</span>${badge(res)}</div><div class="v">${val}</div><div class="r">Requirement: ${req}</div><div class="r">${margin}</div>${pct!=null?`<div class="gauge"><i style="width:${Math.min(100,pct)}%;background:${res==="PASS"?"var(--pass)":"var(--fail)"}"></i></div>`:""}</div>`;
 return `<div class="dh"><div><h2>${esc(x.formula)}</h2><div class="sub">Screening result</div></div><div class="verdict ${f}">${f==="INCOMPLETE"?"NOT EVALUABLE":f}</div></div>
 ${expl}
 <h3>Screening values</h3><div class="checks">${chk("Applicability domain",x.ad_result,x.applicability_domain+" · distance "+dist,`distance ≤ ${fmt(t.ad,2)}`,x.ad_result==="PASS"?"Prediction is reliable":"Prediction is less reliable",Math.min(100,adR*100))}${chk("Ehull (stability)",x.ehull_result,e==null?"—":fmt(e,1)+" meV/atom",`≤ ${t.ehull} meV/atom`,e==null?"Not available in dataset":(ehM>=0?`${fmt(ehM,1)} below the limit`:`${fmt(-ehM,1)} above the limit`),e==null?null:e/t.ehull*100)}${chk("ORR activity",x.orr_result,"log10(k*) "+fmt(p,2),`≥ ${t.orr} (LSC benchmark)`,(orrM>=0?`${fmt(orrM,2)} above the benchmark`:`${fmt(-orrM,2)} below the benchmark`)+` · k* = ${fmt(k)} cm/s`,Math.max(0,Math.min(100,100+orrM*50)))}</div>`};
window.detail=async id=>{const x=await api(`/datasets/${S.ds.id}/results/${id}`);S.sel=x;$("#mbody").innerHTML=dhtml(x);$("#modal").classList.remove("hidden")};
// ---------- Predict a single cathode (uses the saved model + saved training data) ----------
const checksHtml=o=>{
 const t=o.thresholds,p=o.pred_log,e=o.ehull,orrM=p-t.orr,ehM=e==null?null:t.ehull-e,adR=o.dist/t.ad;
 const chk=(ti,res,val,req,margin,pct)=>`<div class="chk ${String(res).replace(/ /g,"")}"><div class="t"><span>${ti}</span>${badge(res)}</div><div class="v">${val}</div><div class="r">Requirement: ${req}</div><div class="r">${margin}</div>${pct!=null?`<div class="gauge"><i style="width:${Math.min(100,pct)}%;background:${res==="PASS"?"var(--pass)":"var(--fail)"}"></i></div>`:""}</div>`;
 return `<div class="checks one">${chk("Applicability domain",o.ad_result,(o.ad==="INSIDE"?"INSIDE":"OUTSIDE")+" · distance "+fmt(o.dist,2),`distance ≤ ${fmt(t.ad,2)}`,o.ad_result==="PASS"?"Prediction is reliable":"Prediction is less reliable",Math.min(100,adR*100))}${chk("Ehull (stability)",o.ehull_result,e==null?"not entered":fmt(e,1)+" meV/atom",`≤ ${t.ehull} meV/atom`,e==null?"Enter Ehull to check stability":(ehM>=0?`${fmt(ehM,1)} below the limit`:`${fmt(-ehM,1)} above the limit`),e==null?null:e/t.ehull*100)}${chk("ORR activity",o.orr_result,"log10(k*) "+fmt(p,2),`≥ ${t.orr} (LSC benchmark)`,orrM>=0?`${fmt(orrM,2)} above the benchmark`:`${fmt(-orrM,2)} below the benchmark`,Math.max(0,Math.min(100,100+orrM*50)))}</div>`};
const whyHtml=o=>{
 const t=o.thresholds,f=o.final,p=o.pred_log,e=o.ehull,orrM=p-t.orr,ehM=e==null?null:t.ehull-e,dist=fmt(o.dist,2),fails=[];
 if(o.ad_result==="FAIL")fails.push(`It lies <b>outside the applicability domain</b> – its distance of ${dist} is above the limit of ${fmt(t.ad,2)}, so the model’s prediction for it is less reliable.`);
 if(o.ehull_result==="FAIL")fails.push(`Its <b>Ehull</b> of ${fmt(e,1)} meV/atom is ${fmt(-ehM,1)} above the ${t.ehull} meV/atom limit, so it is not stable enough.`);
 if(o.orr_result==="FAIL")fails.push(`Its predicted <b>log10(k*)</b> of ${fmt(p,2)} is ${fmt(-orrM,2)} below the ${t.orr} benchmark, so it is not active enough.`);
 if(f==="PASS")return `<div class="expl good"><b>Result: PASS – it meets every screening condition.</b><ul><li>Applicability domain: inside – distance ${dist} is within the limit of ${fmt(t.ad,2)}.</li><li>Stability: Ehull of ${fmt(e,1)} meV/atom is within the ${t.ehull} limit (${fmt(ehM,1)} below it).</li><li>Activity: predicted log10(k*) of ${fmt(p,2)} is ${fmt(orrM,2)} above the ${t.orr} benchmark.</li></ul></div>`;
 if(f==="FAIL")return `<div class="expl bad"><b>Result: FAIL – reason:</b><ul>${fails.map(m=>`<li>${m}</li>`).join("")}</ul></div>`;
 return `<div class="expl"><b>Result: could not be fully evaluated.</b> ${(o.not_available||[]).map(esc).join(" ")}${fails.length?`<ul>${fails.map(m=>`<li>${m}</li>`).join("")}</ul>`:"<br>Everything that could be checked passed."}</div>`};
const cmpHtml=c=>{
 const out=c.ranges.filter(r=>!r.inside);
 return `<h3 style="margin-top:16px">Compared with the saved training data</h3><p class="small muted">The model was trained on ${c.n_training} cathodes. The values you entered are compared with that saved data:</p>
  ${out.length?`<div class="note"><b>${out.length} of ${c.ranges.length} descriptors</b> lie outside the range seen in training, so the prediction is an extrapolation: ${out.map(r=>`${esc(r.feature)} (${fmt(r.value,3)}; training range ${fmt(r.min,3)} to ${fmt(r.max,3)})`).join(", ")}.</div>`:'<div class="note ok">All entered descriptors lie inside the range of the training data.</div>'}
  <div class="tw"><table><thead><tr><th>Most similar training cathodes</th><th>Distance</th><th>Experimental log10(k*)</th></tr></thead><tbody>${c.nearest.map(n=>`<tr><td><b>${esc(n.formula)}</b></td><td>${fmt(n.distance,2)}</td><td>${fmt(n.log_k,2)}</td></tr>`).join("")}</tbody></table></div>`};
const predHtml=o=>`<div class="card pres"><div class="pv ${o.final}"><div><div class="pv-s">${esc(o.formula)}</div><div class="pv-n">${o.final==="INCOMPLETE"?"NOT EVALUABLE":o.final}</div></div><div class="pv-r"><div class="pv-k">${fmt(o.pred_log,2)}</div><div class="pv-s">predicted log10(k*)</div><div class="pv-s">k* = ${fmt(o.pred_k)} cm/s</div></div></div>
  ${whyHtml(o)}<h3>Screening values</h3>${checksHtml(o)}
  ${o.imputed.length?`<p class="small muted">${o.imputed.length} descriptor value(s) were left blank and filled with the training median: ${o.imputed.map(esc).join(", ")}.</p>`:""}
  ${cmpHtml(o.compare)}
  <p class="small muted" style="margin:10px 0 0">Predicted by the saved ${esc(o.model.name)} model (trained on ${o.model.trained_on} cathodes).</p></div>`;
P.predict=()=>{
 if(!S.ds)return $("#main").innerHTML=need();const t=S.ds.train;
 if(!t)return $("#main").innerHTML='<div class="note">Train the models first – open <a href="#" onclick="go(\'training\');return false">ML Training</a>. The trained model and training data are saved automatically and used on this page.</div>';
 const lab={};(t.shap||[]).forEach(x=>lab[x.feature]=x.label);const st=t.feature_stats||{};
 $("#main").innerHTML=`<h2>Predict a Single Cathode</h2><p class="muted">Enter the descriptor values of one cathode. They are compared with the saved training data and the saved ${esc(t.primary)} model predicts log10(k*) → PASS or FAIL, with the reason if it fails.</p>
  <div class="pred-grid"><div class="card"><h3>Descriptor values</h3><p class="small muted">${t.features.length} descriptors selected by the feature selection (the only ones the model uses). Blank values are filled with the training median.</p>
   <label>Cathode name / formula (optional)<input id="pf_name" placeholder="e.g. La0.6Sr0.4CoO3" maxlength="60"></label>
   <div class="fgrid">${t.features.map(c=>{const s=st[c]||{};return `<label class="fld"><span class="fl-k">${esc(c)}</span><span class="fl-l">${esc(lab[c]||c)}</span><input type="number" step="any" data-f="${esc(c)}" placeholder="${s.median!=null?"e.g. "+fmt(s.median,3):"value"}"><span class="fl-h">${s.min!=null?`training range ${fmt(s.min,3)} to ${fmt(s.max,3)}`:""}</span></label>`}).join("")}</div>
   <h3 style="margin-top:18px">Stability</h3>
   <label class="fld" style="max-width:340px"><span class="fl-k">Ehull</span><span class="fl-l">Energy above hull (meV/atom) – needed for a full PASS / FAIL</span><input type="number" step="any" id="pf_eh" placeholder="e.g. 30"><span class="fl-h">Limit: ≤ 57 meV/atom</span></label>
   <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap"><button class="btn" id="pbtn" onclick="runPredict()">Predict</button><button class="btn sec" onclick="fillPred()">Fill with typical values</button><button class="btn sec" onclick="clearPred()">Clear</button></div></div>
  <div id="predres" class="pred-res"><div class="card pres empty"><div class="ph-ico">⬡</div><b>Result appears here</b><p class="small muted">Enter the values on the left and press <b>Predict</b>.</p></div></div></div>`;
 document.querySelectorAll("[data-f],#pf_eh,#pf_name").forEach(i=>i.addEventListener("keydown",e=>{if(e.key==="Enter")runPredict()}));
};
window.fillPred=()=>{const st=S.ds.train.feature_stats||{};document.querySelectorAll("[data-f]").forEach(i=>{const s=st[i.dataset.f];if(s&&s.median!=null)i.value=+s.median.toPrecision(5)})};
window.clearPred=()=>{document.querySelectorAll("[data-f],#pf_eh,#pf_name").forEach(i=>i.value="");$("#predres").innerHTML='<div class="card pres empty"><div class="ph-ico">⬡</div><b>Result appears here</b><p class="small muted">Enter the values on the left and press <b>Predict</b>.</p></div>'};
window.runPredict=async()=>{
 const values={};document.querySelectorAll("[data-f]").forEach(i=>{if(i.value.trim()!=="")values[i.dataset.f]=i.value});
 if(!Object.keys(values).length)return toast("Enter at least one descriptor value.");
 const b=$("#pbtn");b.disabled=true;b.textContent="Predicting…";
 try{const o=await api(`/datasets/${S.ds.id}/predict`,{json:{values,ehull:$("#pf_eh").value,formula:$("#pf_name").value}});$("#predres").innerHTML=predHtml(o)}
 catch(e){toast(e.message);$("#predres").innerHTML=`<div class="note bad">${esc(e.message)}</div>`}
 finally{b.disabled=false;b.textContent="Predict"}};

P.export=()=>{if(!S.ds)return $("#main").innerHTML=need();const s=S.ds.summary;if(!s)return $("#main").innerHTML='<div class="note">Run the screening first (ML Training page).</div>';const n=S.ds.filename.replace(/\.[^.]+$/,"");
 $("#main").innerHTML=`<h2>Export Results</h2><div class="card"><p>All files are sorted by <b>rank</b> (closest to passing first); Excel rows are coloured <span style="background:#C6EFCE;padding:0 6px">green</span> / <span style="background:#FFE0B2;padding:0 6px">orange</span> / <span style="background:#F8C9C9;padding:0 6px">red</span>.</p>
 <p>Complete workbook sheets: <b>Screening Results</b> (${s.total}), <b>PASS Cathodes</b> (${s.PASS}), <b>FAIL Cathodes</b> (${s.FAIL}), Notes.</p>${s.PASS===0?'<div class="note">No cathode has a full PASS, so the PASS file will contain an empty sheet.</div>':""}
 <p><button class="btn" onclick="dl('/datasets/${S.ds.id}/export/all','${n}_all.xlsx')">Download Complete Results Excel</button> <button class="btn" onclick="dl('/datasets/${S.ds.id}/export/pass','${n}_PASS.xlsx')">Download PASS Cathodes Excel</button> <button class="btn sec" onclick="dl('/datasets/${S.ds.id}/export/fail','${n}_FAIL.xlsx')">Download FAIL Cathodes Excel</button> <button class="btn sec" onclick="dl('/datasets/${S.ds.id}/export/csv','${n}_results.csv')">Download Results CSV</button></p></div>`};
show();