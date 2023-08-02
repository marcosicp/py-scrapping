import { Component } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';

@Component({
  selector: 'total-value-component',
  template: `
    <input
      type="checkbox"
      style="left: 5px; opacity: 1;"
      (click)="buttonClicked($event)"
      [checked]="cellValue"
    />
  `,
})
export class TotalValueRenderer implements ICellRendererAngularComp {
  public cellValue!: string;
  public params: any = false;
  // gets called once before the renderer is used
  agInit(params: ICellRendererParams): void {
    this.params = params;
    // debugger;
    this.cellValue = this.getValueToDisplay(params);
  }

  // gets called whenever the user gets the cell to refresh
  refresh(params: ICellRendererParams) {
    // set value into cell again
    this.cellValue = this.getValueToDisplay(params);
    return true;
  }

  buttonClicked(e: any) {
    this.params.clicked(this.params.data);
  }

  getValueToDisplay(params: ICellRendererParams) {
    return params.valueFormatted ? params.valueFormatted : params.data.selected;
  }
}
