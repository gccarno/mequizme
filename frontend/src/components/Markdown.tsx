import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Question/answer text is markdown; links open in a new tab so a quiz isn't lost. */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={`md ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
