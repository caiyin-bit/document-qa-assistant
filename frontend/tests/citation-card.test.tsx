import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { CitationCard } from '../components/citation-card';

describe('CitationCard', () => {
  it('renders filename and page badge', () => {
    const { getByText } = render(
      <CitationCard citations={[{
        doc_id: 'a', filename: '腾讯2025.pdf', page_no: 12,
        snippet: '一段 snippet', score: 0.8,
      }]} />
    );
    expect(getByText('腾讯2025.pdf')).toBeTruthy();
    expect(getByText(/p\.12|第 12 页/)).toBeTruthy();
  });

  it('shows count for multiple sources', () => {
    const { getByText } = render(
      <CitationCard citations={[
        { doc_id: 'a', filename: 'x.pdf', page_no: 1, snippet: 's', score: 0.8 },
        { doc_id: 'a', filename: 'x.pdf', page_no: 2, snippet: 's', score: 0.7 },
      ]} />
    );
    expect(getByText(/来源（2）/)).toBeTruthy();
  });

  it('renders nothing when citations empty', () => {
    const { container } = render(<CitationCard citations={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
