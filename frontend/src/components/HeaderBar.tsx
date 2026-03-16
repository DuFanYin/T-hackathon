import type { FC, ReactNode } from 'react';

interface HeaderBarProps {
  title: string;
  onRefresh?: () => void;
  extra?: ReactNode;
}

export const HeaderBar: FC<HeaderBarProps> = ({ title, onRefresh, extra }) => {
  return (
    <div className="header">
      <div className="header-title">{title}</div>
      <div className="row">
        {onRefresh && (
          <button className="btn" onClick={onRefresh}>
            Refresh
          </button>
        )}
        {extra}
      </div>
    </div>
  );
};

