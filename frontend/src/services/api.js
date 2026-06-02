import axios from "axios";
const api = axios.create({ baseURL: "/api/v1" });
export const videoAPI = {
  upload: (file, onProgress) => {
    const form = new FormData();
    form.append("file", file);
    return api.post("/video/upload", form, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: e => onProgress && onProgress(Math.round((e.loaded * 100) / e.total)),
    });
  },
  list: () => api.get("/video/"),
  get: (id) => api.get(`/video/${id}`),
};
export const eventsAPI = { list: (params) => api.get("/events/", { params }) };
export const alertsAPI = {
  list: (unreadOnly = false) => api.get("/alerts/", { params: { unread_only: unreadOnly } }),
  markRead: (id) => api.patch(`/alerts/${id}/read`),
};
export const facesAPI = {
  addSuspect: (name, notes, imageFile) => {
    const form = new FormData();
    form.append("name", name); form.append("notes", notes); form.append("image", imageFile);
    return api.post("/faces/suspects", form);
  },
  listSuspects: () => api.get("/faces/suspects"),
};
export default api;
