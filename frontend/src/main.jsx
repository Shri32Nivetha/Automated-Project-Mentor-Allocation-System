import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import { AuthProvider } from "./auth.jsx";
import { ToastProvider, ConfirmProvider } from "./ui.jsx";
import "@fontsource-variable/inter";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <BrowserRouter>
    <ToastProvider>
      <ConfirmProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ConfirmProvider>
    </ToastProvider>
  </BrowserRouter>
);
