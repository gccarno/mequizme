import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { AttemptReview } from "./pages/AttemptReview";
import { Flashcards } from "./pages/Flashcards";
import { History } from "./pages/History";
import { Library } from "./pages/Library";
import { QuizRunner } from "./pages/QuizRunner";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function App() {
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="top">
        <NavLink to="/" className="brand">
          mequizme
        </NavLink>
        <nav aria-label="Main">
          <NavLink to="/" end>
            Library
          </NavLink>
          <NavLink to="/history">History</NavLink>
        </nav>
      </header>
      <main id="main">
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/study" element={<Flashcards />} />
          <Route path="/attempt/:id" element={<QuizRunner />} />
          <Route path="/attempt/:id/review" element={<AttemptReview />} />
          <Route path="/history" element={<History />} />
          <Route
            path="*"
            element={
              <p className="page">
                This page doesn't exist. <NavLink to="/">Go to the library</NavLink>.
              </p>
            }
          />
        </Routes>
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
