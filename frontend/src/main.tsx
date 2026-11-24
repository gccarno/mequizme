import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "./styles.css";

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { useAiStatus } from "./components/Tutor";
import { AttemptReview } from "./pages/AttemptReview";
import { Drafts } from "./pages/Drafts";
import { Flashcards } from "./pages/Flashcards";
import { History } from "./pages/History";
import { Library } from "./pages/Library";
import { Progress } from "./pages/Progress";
import { QuizRunner } from "./pages/QuizRunner";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

/** Shown when AI is on, or when drafts are waiting even with it off. */
function TutorLink() {
  const ai = useAiStatus();
  const drafts = useQuery({ queryKey: ["draft-count"], queryFn: api.draftCount });
  const n = drafts.data?.count ?? 0;
  if (!ai.data?.available && n === 0) return null;
  return (
    <NavLink to="/drafts">
      AI tutor
      {n > 0 && (
        <span className="nav-count">
          {n}
          <span className="visually-hidden"> drafts to review</span>
        </span>
      )}
    </NavLink>
  );
}

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
          <NavLink to="/progress">Progress</NavLink>
          <NavLink to="/history">History</NavLink>
          <TutorLink />
        </nav>
      </header>
      <main id="main">
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/study" element={<Flashcards />} />
          <Route path="/attempt/:id" element={<QuizRunner />} />
          <Route path="/attempt/:id/review" element={<AttemptReview />} />
          <Route path="/progress" element={<Progress />} />
          <Route path="/history" element={<History />} />
          <Route path="/drafts" element={<Drafts />} />
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
