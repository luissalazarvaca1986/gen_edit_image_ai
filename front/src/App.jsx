import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from './api.js';

const ASPECTS = ['1:1', '3:4', '4:3', '2:3', '3:2', '9:16', '16:9'];
const DEFAULT_NEGATIVE = 'lowres, blurry, bad anatomy, deformed, watermark, text';
const isPending = (g) => g.status === 'queued' || g.status === 'running';

export default function App() {
  const [models, setModels] = useState([]);
  const [history, setHistory] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const [form, setForm] = useState({
    model: '', prompt: '', negative_prompt: DEFAULT_NEGATIVE,
    aspect: '1:1', steps: 25, cfg_scale: 7, seed: -1, strength: 0.6,
  });
  // Referencia: archivo subido ({file, preview}) o una generación previa ({id, preview})
  const [reference, setReference] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef(null);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const refresh = useCallback(async () => {
    try {
      setHistory(await api.getGenerations());
    } catch (e) {
      setError(`No se pudo cargar el historial: ${e.message}`);
    }
  }, []);

  useEffect(() => {
    api.getModels().then((m) => {
      setModels(m);
      setForm((f) => ({ ...f, model: f.model || m[0] || '' }));
    }).catch((e) => setError(`No se pudieron cargar los modelos: ${e.message}`));
    refresh();
  }, [refresh]);

  // Mientras haya algo en cola o generándose, se consulta el progreso cada segundo
  const anyPending = history.some(isPending);
  useEffect(() => {
    if (!anyPending) return undefined;
    const t = setInterval(refresh, 1000);
    return () => clearInterval(t);
  }, [anyPending, refresh]);

  const selected = history.find((g) => g.id === selectedId) ?? history[0];

  const pickFile = (file) => {
    if (!file || !file.type.startsWith('image/')) return;
    if (reference?.file) URL.revokeObjectURL(reference.preview);
    setReference({ file, preview: URL.createObjectURL(file), name: file.name });
  };

  const clearReference = () => {
    if (reference?.file) URL.revokeObjectURL(reference.preview);
    setReference(null);
  };

  const useAsReference = (g) => {
    clearReference();
    setReference({ id: g.id, preview: g.output_url, name: `Generación #${g.id}` });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const reuseParams = (g) => {
    setForm((f) => ({
      ...f,
      model: models.includes(g.model) ? g.model : f.model,
      prompt: g.prompt,
      negative_prompt: g.negative_prompt,
      steps: g.steps,
      cfg_scale: g.cfg_scale,
      seed: g.seed,
      strength: g.strength ?? f.strength,
    }));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    const fd = new FormData();
    Object.entries(form).forEach(([k, v]) => fd.append(k, v));
    if (reference?.file) fd.append('reference', reference.file);
    if (reference?.id) fd.append('reference_id', reference.id);
    try {
      const g = await api.generate(fd);
      setSelectedId(g.id);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (g) => {
    if (!window.confirm(`¿Eliminar la generación #${g.id}?`)) return;
    try {
      await api.deleteGeneration(g.id);
      if (reference?.id === g.id) clearReference();
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const removeAll = async () => {
    if (!window.confirm('¿Eliminar TODO el historial y sus imágenes? No se puede deshacer.')) return;
    try {
      await api.deleteAllGenerations();
      if (reference?.id) clearReference();
      setSelectedId(null);
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="app">
      <header className="topbar">
        <h1>Gen AI <span>· local</span></h1>
        <span className="muted">{models.length ? `${models.length} modelo(s) en ./models` : 'sin modelos'}</span>
      </header>

      <main className="layout">
        <form className="panel form" onSubmit={submit}>
          <label>Modelo
            <select value={form.model} onChange={set('model')}>
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>

          <label>Prompt
            <textarea rows={5} value={form.prompt} onChange={set('prompt')} required
              placeholder="Describe la imagen que quieres generar…" />
          </label>

          <div className="field">
            <span className="label">Imagen de referencia <em>(opcional)</em></span>
            {reference ? (
              <div className="ref-preview">
                <img src={reference.preview} alt="Referencia" />
                <div>
                  <strong>{reference.name}</strong>
                  <button type="button" className="link danger" onClick={clearReference}>Quitar</button>
                </div>
              </div>
            ) : (
              <div
                className={`dropzone${dragging ? ' over' : ''}`}
                onClick={() => fileInput.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files[0]); }}
              >
                Arrastra una imagen o haz clic para elegirla
              </div>
            )}
            <input ref={fileInput} type="file" accept="image/*" hidden
              onChange={(e) => { pickFile(e.target.files[0]); e.target.value = ''; }} />
          </div>

          {reference ? (
            <label>Fuerza de cambio: <b>{Number(form.strength).toFixed(2)}</b>
              <input type="range" min="0.05" max="1" step="0.05" value={form.strength} onChange={set('strength')} />
              <small className="muted">Bajo = se parece a la referencia · Alto = cambia más</small>
            </label>
          ) : (
            <label>Proporción
              <select value={form.aspect} onChange={set('aspect')}>
                {ASPECTS.map((a) => <option key={a}>{a}</option>)}
              </select>
            </label>
          )}

          <button type="button" className="link" onClick={() => setShowAdvanced((v) => !v)}>
            {showAdvanced ? '▾' : '▸'} Opciones avanzadas
          </button>
          {showAdvanced && (
            <div className="advanced">
              <label>Prompt negativo
                <textarea rows={2} value={form.negative_prompt} onChange={set('negative_prompt')} />
              </label>
              <div className="row">
                <label>Pasos<input type="number" min="1" max="150" value={form.steps} onChange={set('steps')} /></label>
                <label>CFG<input type="number" min="1" max="30" step="0.5" value={form.cfg_scale} onChange={set('cfg_scale')} /></label>
                <label>Semilla<input type="number" value={form.seed} onChange={set('seed')} title="-1 = aleatoria" /></label>
              </div>
            </div>
          )}

          <button className="primary" disabled={submitting || !form.model}>
            {submitting ? 'Enviando…' : 'Generar'}
          </button>
          {error && <pre className="error">{error}</pre>}
        </form>

        <section className="panel viewer">
          {selected ? <Viewer g={selected} onUseRef={useAsReference} onReuse={reuseParams} onDelete={remove} />
            : <div className="empty">Aquí aparecerá tu imagen</div>}
        </section>
      </main>

      <section className="history">
        <div className="history-head">
          <h2>Historial <span className="muted">({history.length})</span></h2>
          {history.length > 0 && <button className="danger" onClick={removeAll}>Borrar todo</button>}
        </div>
        <div className="grid">
          {history.map((g) => (
            <button key={g.id} className={`thumb${selected?.id === g.id ? ' active' : ''}`}
              onClick={() => setSelectedId(g.id)} title={g.prompt}>
              {g.output_url ? <img src={g.output_url} alt={g.prompt} loading="lazy" />
                : <div className={`placeholder ${g.status}`}>{statusLabel(g)}</div>}
              <span className="badge">#{g.id}{g.reference_path ? ' · ref' : ''}</span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function statusLabel(g) {
  if (g.status === 'queued') return 'En cola…';
  if (g.status === 'running') {
    const { step, total } = g.progress;
    return step ? `Generando ${step}/${total}` : 'Cargando modelo…';
  }
  if (g.status === 'error') return 'Error';
  return '';
}

function Viewer({ g, onUseRef, onReuse, onDelete }) {
  const pct = g.progress.total ? Math.round((g.progress.step / g.progress.total) * 100) : 0;
  return (
    <div className="viewer-inner">
      <div className="stage">
        {g.output_url ? <img src={g.output_url} alt={g.prompt} />
          : (
            <div className={`placeholder big ${g.status}`}>
              <span>{statusLabel(g)}</span>
              {g.status === 'running' && <div className="bar"><div style={{ width: `${pct}%` }} /></div>}
              {g.status === 'error' && <pre className="error">{g.error}</pre>}
            </div>
          )}
      </div>
      <div className="meta">
        <p className="prompt">{g.prompt}</p>
        <dl>
          <dt>#</dt><dd>{g.id} · {new Date(g.created_at).toLocaleString()}</dd>
          <dt>Modelo</dt><dd>{g.model}</dd>
          <dt>Tamaño</dt><dd>{g.width}×{g.height}</dd>
          <dt>Pasos / CFG</dt><dd>{g.steps} / {g.cfg_scale}</dd>
          <dt>Semilla</dt><dd>{g.seed}</dd>
          {g.duration_ms && <><dt>Tiempo</dt><dd>{(g.duration_ms / 1000).toFixed(1)} s</dd></>}
          {g.reference_path && <><dt>Referencia</dt><dd>
            <a href={g.reference_url} target="_blank" rel="noreferrer">
              <img className="mini" src={g.reference_url} alt="referencia" />
            </a>
            {g.parent_id ? ` generación #${g.parent_id}` : ' subida'} · fuerza {g.strength}
          </dd></>}
          {g.output_path && <><dt>Archivo</dt><dd><code>.{g.output_path}</code></dd></>}
        </dl>
        <div className="actions">
          {g.output_url && <button onClick={() => onUseRef(g)}>Usar como referencia</button>}
          <button onClick={() => onReuse(g)}>Reutilizar parámetros</button>
          {g.output_url && <a className="btn" href={g.output_url} download={`gen-${g.id}.png`}>Descargar</a>}
          {!isPending(g) && <button className="danger" onClick={() => onDelete(g)}>Eliminar</button>}
        </div>
      </div>
    </div>
  );
}
