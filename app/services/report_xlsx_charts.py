"""
report_xlsx_charts.py - PNG charts for the Excel results report (matplotlib).

Every function returns PNG bytes. Colours are the validated categorical slots
(blue, orange, aqua) on a white surface; thin marks, hairline grid, one axis
per chart (small multiples instead of dual axes).
"""
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt, matplotlib.dates as mdates
import io
import numpy as np, pandas as pd
BLUE,ORANGE,AQUA='#2a78d6','#eb6834','#1baf7a'
INK,INK2,GRID,BAND,SURF='#0b0b0b','#52514e','#e6e6e6','#e3e8ef','#ffffff'
SEQ=['#f4f8fd','#cde2fb','#9ec5f4','#6da7ec','#3987e5','#256abf','#184f95','#0d366b']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.edgecolor':GRID,'axes.labelcolor':INK2,'xtick.color':INK2,'ytick.color':INK2,
  'axes.titlesize':11,'axes.titleweight':'bold','axes.titlecolor':INK,'axes.titlelocation':'left','axes.titlepad':10,'figure.dpi':130,
  'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.color':GRID,'grid.linewidth':0.6,'axes.axisbelow':True,'legend.frameon':False})
def _fin(fig,path=None,note=None):
    if note: fig.text(0.01,0.01,note,fontsize=7.5,color=INK2,ha='left',va='bottom')
    buf=io.BytesIO(); fig.savefig(buf,format='png',bbox_inches='tight',facecolor=SURF,dpi=130); plt.close(fig)
    return buf.getvalue()
def _bars(ax,x,vals,color,fmt,labels=True):
    b=ax.bar(x,vals,color=color,width=0.62,edgecolor=SURF,linewidth=1.2)
    if labels:
        for r,v in zip(b,vals): ax.annotate(fmt(v),(r.get_x()+r.get_width()/2,v),xytext=(0,2),textcoords='offset points',ha='center',va='bottom',fontsize=7.5,color=INK2)
    ax.grid(axis='x',visible=False); return b

def monthly_panels(mt,path=None,unit=''):
    """Small multiples: four monthly measures, one axis each (no dual axes)."""
    labs=mt['label']; x=np.arange(len(labs)); n=len(labs)
    fig,axs=plt.subplots(2,2,figsize=(13,6.4)); lab=n<=8
    spec=[('Extreme share','Extreme readings, share of readings',lambda v:f'{v:.0%}',BLUE,True),
          ('Confirmed share','Confirmed/Materialized Shift, share of readings',lambda v:f'{v:.0%}',BLUE,True),
          ('Sustained deviation (h)','Sustained deviation (Persistent + Confirmed), hours',lambda v:f'{v:.0f}',BLUE,False),
          ('Material changes per day','Material changes per day',lambda v:f'{v:.1f}',BLUE,False)]
    for ax,(col,title,fmt,c,pct) in zip(axs.flat,spec):
        v=mt[col].values; _bars(ax,x,v,c,fmt,labels=True)
        if len(v) and np.isfinite(v).any():
            worst=int(np.nanargmax(v)); ax.patches[worst].set_color(ORANGE)
        ax.set_title(title); ax.set_xticks(x,labs,rotation=0 if n<=8 else 45,ha='center' if n<=8 else 'right')
        if pct:
            ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(0.05 if np.nanmax(v)>0.15 else 0.02)); ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1,decimals=0))
        ax.set_ylim(0,(np.nanmax(v) if len(v) and np.nanmax(v)>0 else 1)*1.18)
    fig.tight_layout(h_pad=2.2)
    return _fin(fig,path,'Orange bar = highest month for that measure.')

def events_and_directions(mt,path=None):
    labs=mt['label']; x=np.arange(len(labs)); n=len(labs)
    fig,(a1,a2)=plt.subplots(1,2,figsize=(13,3.9))
    bottom=np.zeros(n)
    for col,c in [('Investigate',ORANGE),('Review',BLUE),('Monitor',AQUA)]:
        a1.bar(x,mt[col],bottom=bottom,color=c,width=0.62,edgecolor=SURF,linewidth=1.2,label=col); bottom+=mt[col].values
    a1.set_title('Events by action'); a1.set_xticks(x,labs,rotation=0 if n<=8 else 45,ha='center' if n<=8 else 'right'); a1.grid(axis='x',visible=False)
    a1.legend(ncol=3,loc='upper right',fontsize=8)
    w=0.2
    for k,(col,c,h) in enumerate([('Upper – Day',ORANGE,None),('Upper – Night',ORANGE,'////'),('Lower – Day',BLUE,None),('Lower – Night',BLUE,'////')]):
        a2.bar(x+(k-1.5)*w,mt[col],width=w,color=c if h is None else SURF,edgecolor=c,hatch=h,linewidth=1.0,label=col)
    a2.set_title('Extreme readings by direction and time of day'); a2.set_xticks(x,labs,rotation=0 if n<=8 else 45,ha='center' if n<=8 else 'right')
    a2.grid(axis='x',visible=False); a2.legend(ncol=4,loc='upper right',fontsize=8)
    for a in (a1,a2): a.set_ylim(0,a.get_ylim()[1]*1.15)
    fig.tight_layout(); return _fin(fig,path,'Hatched = night. Investigate = Confirmed shift, Review = Persistent, Monitor = shorter events.')

def daily_overview(df,gaps,path=None,unit=''):
    d=df.set_index('Timestamp').Value.resample('D').agg(['mean','min','max'])
    e=df.set_index('Timestamp').resample('D').agg({'ExtremeFlag':'mean','ConfirmedShiftFlag':'sum','State':lambda s:(s=='Persistent').sum()})
    ivl=df.Timestamp.diff().dt.total_seconds().median()/3600
    fig,(a1,a2,a3)=plt.subplots(3,1,figsize=(13,8.2),sharex=True,gridspec_kw={'height_ratios':[1.4,1,1]})
    a1.fill_between(d.index,d['min'],d['max'],color=BAND,linewidth=0,label='Daily min – max')
    a1.plot(d.index,d['mean'],color=BLUE,lw=1.6,label='Daily mean')
    for g in gaps.itertuples(index=False):
        if g.hours>=6: a1.axvspan(g.frm,g.to,color='#fbe3d6',lw=0)
    a1.set_title(f'Daily value ({unit})'); a1.legend(loc='upper left',ncol=3,fontsize=8)
    a1.plot([],[],color='#fbe3d6',lw=6,label='Data gap (6 h or more)'); a1.legend(loc='upper left',ncol=3,fontsize=8)
    a2.bar(e.index,e['State']*ivl,width=0.85,color=BLUE,label='Persistent')
    a2.bar(e.index,e['ConfirmedShiftFlag']*ivl,bottom=e['State']*ivl,width=0.85,color=ORANGE,label='Confirmed shift')
    a2.set_title('Hours in Persistent and Confirmed-shift states per day'); a2.legend(loc='upper left',ncol=2,fontsize=8); a2.set_ylabel('hours')
    a3.bar(e.index,e['ExtremeFlag'],width=0.85,color=BLUE)
    a3.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1,decimals=0)); a3.set_title('Share of readings flagged Extreme per day')
    a3.xaxis.set_major_locator(mdates.MonthLocator()); a3.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    if (d.index.max()-d.index.min()).days<20:
        a3.xaxis.set_major_locator(mdates.DayLocator()); a3.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    elif (d.index.max()-d.index.min()).days<120: a3.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0)); a3.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    for a in (a2,a3): a.grid(axis='x',visible=False)
    fig.tight_layout(h_pad=1.6); return _fin(fig,path)

def hour_heatmap(df,path=None):
    """Share of readings flagged Extreme by hour of day and month (sequential blue)."""
    t=df.assign(h=df.Timestamp.dt.hour,m=df.Timestamp.dt.to_period('M'))
    p=t.pivot_table(index='m',columns='h',values='ExtremeFlag',aggfunc='mean')
    up=t[t.ExtremeDirection=='upper'].groupby('h').size().reindex(range(24),fill_value=0)
    lo=t[t.ExtremeDirection=='lower'].groupby('h').size().reindex(range(24),fill_value=0)
    fig,(a1,a2)=plt.subplots(2,1,figsize=(13,3.2+0.28*len(p)),gridspec_kw={'height_ratios':[len(p)*0.28+0.6,1.3]})
    from matplotlib.colors import ListedColormap
    im=a1.imshow(p.values,aspect='auto',cmap=ListedColormap(SEQ),vmin=0,vmax=max(0.3,float(np.nanmax(p.values)) if p.size else 0.3))
    a1.set_yticks(range(len(p)),[x.strftime('%b %Y') for x in p.index]); a1.set_xticks(range(24),[f'{h:02d}' for h in range(24)])
    a1.grid(False); a1.set_title('Share of readings flagged Extreme, by hour of day and month')
    for s in a1.spines.values(): s.set_visible(False)
    cb=fig.colorbar(im,ax=a1,fraction=0.02,pad=0.01); cb.ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1,decimals=0)); cb.outline.set_visible(False)
    x=np.arange(24); a2.bar(x-0.2,up.values,0.4,color=ORANGE,label='Upper extremes'); a2.bar(x+0.2,lo.values,0.4,color=BLUE,label='Lower extremes')
    a2.set_xticks(x,[f'{h:02d}' for h in range(24)]); a2.set_xlabel('hour of day'); a2.set_title('Upper and lower extremes by hour of day (whole period)')
    a2.legend(ncol=2,loc='upper right',fontsize=8); a2.grid(axis='x',visible=False); a2.set_xlim(a1.get_xlim())
    fig.tight_layout(h_pad=1.4); return _fin(fig,path)

def month_detail(s,gaps,path=None,title='',unit=''):
    fig,ax=plt.subplots(figsize=(14,4.4))
    t=s.Timestamp
    ax.fill_between(t,s.LowerLimit,s.UpperLimit,color=BAND,lw=0,label='Normal range (MA ± 2σ)',step=None)
    ax.plot(t,s.Value,color='#5f6b77',lw=0.8,label='Value')
    up=s[s.ExtremeDirection=='upper']; lo=s[s.ExtremeDirection=='lower']
    ax.scatter(up.Timestamp,up.Value,s=9,color=ORANGE,zorder=3,label=f'Upper extreme ({len(up)})',edgecolors=SURF,linewidths=0.3)
    ax.scatter(lo.Timestamp,lo.Value,s=9,color=BLUE,zorder=3,label=f'Lower extreme ({len(lo)})',edgecolors=SURF,linewidths=0.3)
    cs=s.ConfirmedShiftFlag.astype(bool).values
    if cs.any():
        y0=ax.get_ylim()[0]
        ax.fill_between(t,y0,y0+(s.Value.max()-y0)*0.025,where=cs,color=ORANGE,alpha=0.55,lw=0,label='Confirmed shift',step='mid')
    for g in gaps.itertuples(index=False):
        if t.min()<=pd.Timestamp(g.to) and pd.Timestamp(g.frm)<=t.max(): ax.axvspan(g.frm,g.to,color='#fbe3d6',lw=0)
    ax.set_title(title); ax.set_ylabel(unit); ax.margins(x=0.005)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2 if (t.max()-t.min()).days>10 else 1)); ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax.legend(loc='upper center',bbox_to_anchor=(0.5,-0.12),ncol=5,fontsize=8)
    fig.tight_layout(); return _fin(fig,path,'Pale orange background = data gap. Orange strip at the bottom = readings in a Confirmed/Materialized Shift.')
