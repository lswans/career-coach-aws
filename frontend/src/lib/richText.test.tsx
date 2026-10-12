import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { richText } from './richText';

describe('richText', () => {
  it('turns **bold** into <strong>', () => {
    render(<p>{richText('Focus on **Cloud Deployment** and **Live Coding** next.')}</p>);
    expect(screen.getByText('Cloud Deployment').tagName).toBe('STRONG');
    expect(screen.getByText('Live Coding').tagName).toBe('STRONG');
  });

  it('leaves an unfinished ** alone while the reply is still streaming', () => {
    const { container } = render(<p>{richText('Focus on **Cloud Depl')}</p>);
    expect(container.textContent).toBe('Focus on **Cloud Depl');
    expect(container.querySelector('strong')).toBeNull();
  });

  it('never turns model text into HTML', () => {
    const { container } = render(<p>{richText('<img src=x onerror=alert(1)> **ok**')}</p>);
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toBe('<img src=x onerror=alert(1)> ok');
  });
});
