async function request(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* sin cuerpo JSON */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return res.status === 204 ? null : res.json();
}

export const getModels = () => request('/api/models');
export const getGenerations = () => request('/api/generations?limit=200');
export const generate = (formData) => request('/api/generate', { method: 'POST', body: formData });
export const deleteGeneration = (id) => request(`/api/generations/${id}`, { method: 'DELETE' });
export const deleteAllGenerations = () => request('/api/generations', { method: 'DELETE' });
