"""Small append-only suffix journal. Original V8 DB remains a pinned parent."""
import fcntl,hashlib,json,os,sqlite3
from pathlib import Path
from .recovery import need,sha

def encode(v):return json.dumps(v,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(encode(v).encode()).hexdigest()

class Journal:
    def __init__(self,path,*,migration):
        self.path=Path(path);need(not self.path.exists(),'new durable DB required')
        self.path.parent.mkdir(exist_ok=False)
        self.lock=(self.path.parent/'owner.lock').open('x')
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.db=sqlite3.connect(self.path);self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE events(seq INTEGER PRIMARY KEY,kind TEXT,payload TEXT,previous TEXT,sha256 TEXT UNIQUE)')
        self.db.execute('CREATE TABLE processed(model_index INTEGER PRIMARY KEY,call_id TEXT UNIQUE,record_sha256 TEXT)')
        self.tail=None;self.count=0;self.append('migration',migration)
    def append(self,kind,payload):
        row={'seq':self.count,'kind':kind,'payload':payload,'previous':self.tail};h=digest(row)
        with self.db:
            self.db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(self.count,kind,encode(payload),self.tail,h))
            if kind=='action_processed':
                self.db.execute('INSERT INTO processed VALUES(?,?,?)',(payload['model_index'],payload['call_id'],payload['record_sha256']))
        self.tail=h;self.count+=1;return h
    def processed(self,index,call_id):
        return self.db.execute('SELECT 1 FROM processed WHERE model_index=? OR call_id=?',(index,call_id)).fetchone() is not None
    def verify(self):
        need(self.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','suffix SQLite integrity failed')
        tail=None
        for seq,kind,raw,prev,h in self.db.execute('SELECT * FROM events ORDER BY seq'):
            need(prev==tail and digest({'seq':seq,'kind':kind,'payload':json.loads(raw),'previous':prev})==h,'journal hash chain differs');tail=h
        need(tail==self.tail,'journal tail differs')
        return {'journal_records':self.count,'journal_tail_sha256':self.tail,'database_sha256':sha(self.path)}
    def close(self):self.db.close();self.lock.close()
