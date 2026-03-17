import type { FC, ReactNode } from 'react';

interface HeaderBarProps {
  title: string;
  extra?: ReactNode;
}

export const HeaderBar: FC<HeaderBarProps> = ({ title, extra }) => {
  return (
    <div className="mb-1 flex items-center justify-between gap-3">
      <div>
        <h1 className="m-0 text-lg font-medium tracking-tight text-slate-50">{title}</h1>
        <p className="m-0 mt-0.5 text-xs text-slate-400">
          Control and observe your trading engine in real time.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {extra}
      </div>
    </div>
  );
};

