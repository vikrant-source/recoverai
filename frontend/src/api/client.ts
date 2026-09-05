import axios from 'axios';

/**
 * Shared axios instance.
 * The Vite proxy forwards /api/* and /health to http://localhost:8000
 * so no absolute URL is needed in development.
 */
const client = axios.create({
  baseURL: '/',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

export default client;
